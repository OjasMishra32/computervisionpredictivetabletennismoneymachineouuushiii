# COURTSIDE: Q&A prep (team sheet)

For the 5-minute talk plus Q&A, Sun Oct 4, 1:00–3:00 PM EDT, Matthews Suite. Every team member should be able to
give every answer below (track rule: "Every team member should be able to explain the strategy"). Each answer is
2–3 sentences: the answer, then the number, then the file. Numbers were read from the repo on 2026-10-03
around 22:40 UTC. If the paper or a results file changes, the file wins. Paper, video and deck edits are in
`research/compliance/INTEGRATION_TODO.md`.

Merged from five reviewer passes (Jane Street, Citadel PM, microstructure, UF faculty, organizer) and a readiness
check, plus the organizer's two questions to us (Dom: latency under 3 s, and capital capacity).

**Red-team update, about 23:45 UTC Oct 3:** Q1, Q2, Q5, Q6 and Q10 gained lines from new results, and §6 adds three
questions (Q26–Q28) with the new numbers. Sources: `results/redteam/` (`bash run.sh redteam`), `results/e2e/summary.json`.
The deck's backup slides Q11–Q14 carry Q4, Q5/Q6, Q1 and Q2/Q12.

---

## 0. If you only remember one thing (60 seconds, say it like this)

> "Speed is the edge, and we measured it. Wallets that trade in the first 3 seconds after a point make money
> after fees in every month, in sample and held out. Everyone else loses, and copying the same trades 3 seconds
> later loses. That part is measured on public tapes (`results/alpha/alpha.json`).
>
> Then we asked what a computer-vision trader would need to join that tier. Our vision engine makes a call in
> 4.6 ms on a GPU, and our own pipeline adds about a tenth of a second. The binding constraint is the video feed we
> would have to license and the venue's 1-second order hold. Our pre-registered answer: the call has to reach
> the venue about 0.9 s before the umpire logs the point. At a 1-second licensed feed that is break-even:
> +$4 a day held out, −0.38¢ a share.
>
> A post hoc reading of the umpire's lag makes it +$57 to +$94 a day. Another reading of the same data loses
> $17 a day, and a replay on nine real order books loses at every delay we tried. So we do not claim a bankable
> CV P&L. We claim a price on each second of speed, and we name the one number that decides it: the lag from
> bounce to umpire stamp, which a single session with a licensed feed would measure."

The short version: **speed is measured, the CV P&L is a bracket, and the break-even latency is the result.**

---

## 1. How to explain the 1 s baseline honestly

**What it is.** 1 s is the *assumed* glass-to-glass latency of a licensed low-latency betting-video feed. Vendors
claim 0.5–8 s, none of them for tennis, and we bought nothing (`results/tier0/latency_sweep.json::sources`,
`never_claim`). We evaluate the CV trader there because it is a realistic best case for anyone who buys video,
and because that is where the answer changes sign.

**What it is not.** It is not a measurement of a feed we have, and it is not a tuned parameter. The full curve
from 0 to 60 s is shown (Fig. 3). We fixed 1 s as the headline after the sweep's burned-OOS cells had been
computed (sweep peeks 20:16–20:59 UTC in `results/oos_peeks.log`; replay protocol `0e083ed` at 21:14 UTC). So
call it a presentation choice and disclose it.

**The six readings at V = 1 s** (`results/tier0/latency_sweep.json::video_own120.<reading>["1"]`; $/day IS / burned
OOS; burned = non-blind). Say them in this order:

| Reading of the unmeasured timing | IS $/day | OOS $/day | OOS ¢/share [95 % CI] | Sharpe IS / OOS | Status |
|---|---|---|---|---|---|
| **Pre-registered**: stamp lag L = 2.0 s (per-tournament timing, revised after first P&L: V3) | +15 | **+4** | **−0.38** [−2.08, 1.21] | 2.1 / 0.3 | primary; break-even 1.09 / 1.01 s |
| Post hoc: L = 3.14 s inferred from fast-tier prints | +94 | +57 | +0.66 [0.10, 1.19] | 11.9 / 8.8 | assumes courtside humans |
| Same inference, applied per point (stamp-calibrated) | −17 | −17 | −1.92 [−5.38, 1.38] | −3.4 / −3.2 | break-even 0.34 / 0.30 s |
| L = 3.0 s (grid) | +89 | +46 | +0.58 [−0.08, 1.21] | 11.4 / 7.3 | = courtside camera at L = 2.0 s |
| L = 1.0 s (grid) | −6 | −11 | −1.45 [−4.45, 1.39] | −1.4 / −2.3 | stress |
| Stamp-noise reading (V3 alternative; reprice 0.68 s after the bounce) | −17 | −17 | −1.92 [−5.38, 1.38] | −3.4 / −3.2 | loses even at V = 0 |

Two cross-checks that have to be said with the table:
* **Replay on 9 real books** recorded on 2026-10-03, every point called ex ante, V = 1 s, L = 2 s: −0.92¢/share
  [−1.29, −0.57], −$229 marked. All 36 of 36 cells lose, including V = 0 and L = 3 s
  (`results/replay/replay.json::cells`).
* **The sweep's trade set is chosen on outcomes.** It trades only points the market later repriced by ≥ 4¢
  (`research/v2/tier0/RESULTS.md` §8 item 2). The replay trades every point. That gap is the value of knowing
  in advance which points matter, and no live rule supplies it yet (Q4).

**The 20-second spoken version:**
"We don't own a fast feed. We assume a 1-second licensed feed and ask what it is worth. Pre-registered, it breaks
even: the call has to beat the umpire's stamp by about 0.9 s. A post hoc reading of the stamp lag gives $57 a
day, the other reading of the same data gives −$17, and a real-book replay loses. So 1 second is the decision
point for buying a feed. It is not a profit claim."

**Never say:** "calibrated from the data" (say "post hoc inference, assumes courtside humans"); "pre-registered
and conservative" (say "our pre-registered reading"); "stricter readings lose" (say "read the same clocks per
point and it loses"); "this goes live once we license a feed"; "Sharpe 12" without the pre-registered 0.3 next to
it; "our feed", "our camera", "we licensed", "we bought", "live ATP/WTA data"; "11 of 11" or "408 ms" without
"offline, look-ahead feature" (Q10).

---

## 2. Numbers card (memorise these ten)

| # | Number | Source |
|---|---|---|
| 1 | Fast tier positive in 9/9 IS and 3/3 OOS months (11 distinct calendar months; Aug in both); copy 3 s later −1.05¢ IS / −1.59¢ OOS | `results/alpha/alpha.json::headline` |
| 2 | v2 at fast-tier fills: +1.38¢ [1.17, 1.59] IS, **+0.60¢ [0.09, 1.13] OOS**, Sharpe 14.5 / 6.7; fees ×2 OOS −0.34¢ | `results/v2/causal.json`, `cost_stress.json`, `note_metrics.json` |
| 3 | Book reprices a median 1.16 s **before** the umpire stamp (n = 482) | `research/v2/latency/results.json::summary.m1.book_vs_official_T_s` |
| 4 | Break-even feed delay, pre-registered: 1.09 s IS / 1.01 s OOS; call ≥ 0.9 s before the stamp | `latency_sweep.json::breakeven_video_delay.tournament` |
| 5 | CV at 1 s: pre-reg +$4/day OOS (−0.38¢); post hoc +$57/day; stamp-calibrated −$17/day | `latency_sweep.json::video_own120` |
| 6 | Replay, 9 real books: −0.92¢ [−1.29, −0.57] at V = 1; 36/36 cells < 0 | `results/replay/replay.json` |
| 7 | GPU engine: 120 fps, 0 of 102,120 frames dropped, call-ready 4.6 ms p50 / 12.2 ms p99 | `results/engine/online_vs_offline.json::headline` |
| 8 | Live causal engine: 4 of 41 test misses called, all correct (95 % lower bound 51 %), median lead 162.5 ms | `online_vs_offline.json::runs.fp16_cl_fuse_compile_b1_realtime.A_engine_calls` |
| 9 | Capacity: v2 OOS edge holds at $23–34k of capital (1–2×), 5× loses −$25/day | `alpha.json::H_capacity`, `docs/RISK.md` R3 |
| 10 | Costs: feed licence ASSUMPTION $1.25k / $5k / $10k a month → $42 / $167 / $332 a day with VPS; v2 OOS after central costs −$75/day | `results/financials/financials.json` |

---

## 3. The top 25 questions

Format: **question**, then the answer to say, then the evidence. Q1–Q3 are the organizer's (Dom's) own
questions; expect them first. Q4–Q12 are the attacks that can cap Performance at 4 ("lookahead bias or tuning on
the out-of-sample period", REQUIREMENTS item 53) or cost Economic Foundation, the first tie-break after
Performance.

### Organizer concerns (Dom)

**Q1. "You need sub-3-second data. Prove the pipeline can actually trade that fast, frame to order."**
Our own part takes about a tenth of a second, measured piece by piece. The GPU engine is call-ready in 4.6 ms p50
(12.2 ms p99) at 120 fps with 0 of 102,120 frames dropped. WebRTC capture-to-decision on our own stream is 40.7 ms
p50 / 53.9 ms p99. Florida to the venue is 67 ms (London 2 ms), and the venue then holds every taker order 1 s, so
an order is live about 1.1 s after the frame plus the feed delay V. Under 3 s is not enough, though. In our sweep
every reading loses from V = 3 s, and the real bar is a call that reaches the venue about 0.9 s before the
umpire's stamp.
*Say it plainly if asked:* nobody has run camera-to-order in one process on the GPU yet (`engine/README.md` "Known
gaps"). The 40.7 ms WebRTC figure comes from a laptop at 10 fps, because the laptop engine manages only 9–18 fps.
→ **[`results/e2e/summary.json` exists; at 23:15 UTC it had 24 order traces — re-read it before the talk]** "We
measured it end to end in one process: our footage streamed over WebRTC into the vision engine, a call, a paper order
built against a live tennis book. Video in to order ready took 54 ms p50 on a laptop. Add a simulated 1 s feed, 65 ms of
network and the venue's 1 s hold: 2,119 ms, about 0.9 s inside the 3 s bar. The order is unsigned and never sent, and
the calls are table tennis mapped onto a tennis market for timing only." Keys:
`budget_with_1s_simulated_feed.{ours_capture_to_order_ready_ms,network_one_way_ms,total_ms,margin_to_requirement_ms}.p50`.
Evidence: `results/engine/online_vs_offline.json::headline.fp16_cl_fuse_compile_b1_realtime.stream.after_startup`;
`results/webrtc/summary_20261003T212750Z.json::runs[slowmo10_engine].capture_to_decision_ms`;
`results/decay/decay.json::latency_inputs`; `research/v2/feed_latency/LATENCY_SWEEP.md` §2 and §5.

**Q2. "How much capital can this run?"**
Not much, and the paper says so. v2's out-of-sample edge survives only at 1–2× its frozen size: $23k of capital
makes $92/day at 1×, $34k makes $83/day at 2× with a CI that spans zero, and 5× loses $25/day. The CV strategy at
1 s uses $14–29k at a 100-share net cap and 10 matches a day. The binding limit is the stale depth on each
point: a median $222 sits at the old price just before the reprice and $0 half a second later. Raising the net
cap to 1,000 shares loses out of sample (−$51/day at V = 0).
→ **[`results/capacity/capacity.json` exists (capacity workflow, still being audited)]** say the pre-registered line
first: "At the pre-registered 2.0 s lag there is no capacity to speak of: Sharpe 0.9 held out even at the smallest
size." Then the post hoc capacity from its `paragraph`, labelled post hoc. Re-read the file before the talk.
Evidence: `results/alpha/alpha.json::H_capacity.rows`; `docs/RISK.md` R3; `latency_sweep.csv` (capital_usd at
V = 1); `research/v2/latency/results.json::summary.stale_depth`; `research/v2/tier0/RESULTS.md` §3.

**Q3. "Where does a sub-second tennis feed come from, and would anyone sell it to you?"**
Today, nowhere we can reach. The fastest public stream of a Polymarket-listed match we measured is 12.2 s behind
the arena clock (preliminary). Sub-second match video is sold to licensed sportsbooks only, and a spectator camera
is barred by ITF rules and ticket terms. So the strategy needs a licensing deal we do not have, and we say that.
Polymarket US already buys official data and streams (Genius Sports for selected leagues, ATP Tour streaming
rights), so a venue-side route exists. Tennis is not named in the Genius deal.
Evidence: `results/home_stream/sub_second_routes.json::bottom_line` (A8–A11, B2); `docs/paper/PLAN.md` §13 (Genius
scope).

### Attacks that can cap Performance at 4

**Q4. "Your CV trader only trades points the market later moved by ≥ 4¢. How does a live trader know which points
those are? Isn't that lookahead?"**
Yes, the sweep's trade set is selected on outcomes, and we label it that way (`research/v2/tier0/RESULTS.md` §8
item 2). So the sweep prices the value of speed *given* a point worth trading. It is not yet a deployable rule.
Our ex-ante test is the replay, which calls every point on real books, and it loses in all 36 cells: −0.92¢
[−1.29, −0.57] at V = 1 s. Widening the sweep's pool to all 482 points roughly halves the edge (OOS +0.25¢
[−0.35, 0.86] at V = 0).
→ **[if the ex-ante filter run exists, INTEGRATION_TODO C1]** "With an ex-ante filter from the Markov point
leverage, frozen on IS, the replay gives ⟨x⟩¢ [CI]."
Evidence: `results/replay/replay.json::cells`, `research/replay/RESULTS.md`; `research/v2/tier0/RESULTS.md` §3 ("live
pool = all 482 points"), §3 "By realised jump size" (4–5¢ bucket OOS −0.45¢).

**Q5. "The 3.14 s stamp lag was inferred after the pre-registered 2.0 s gave an OOS Sharpe of 0.3. Isn't that
tuning on the out-of-sample period?"**
The pre-registered primary is 2.0 s, and that is our result: break-even at 1 s, +$4/day OOS, −0.38¢/share. The
3.14 s value was written into the tier-0 pre-registration as a grid point, labelled an inference, before any P&L
was run (`research/v2/tier0/PREREG.md` lines 40–52). Promoting it to the headline was a post hoc presentation
choice, and we disclose it as one more trial. Three caveats we volunteer. That PREREG was committed together with
its results (`a5769c7`), so the ordering rests on its timestamp and the peek log (OOS grid run at 17:29 UTC,
`results/oos_peeks.log` line 5). Both Table 2 columns use the per-tournament timing reading, a verifier revision
made after the first P&L run (`DEVIATIONS.md` V3); it keeps the pre-registered median and lowers Sharpe, since
per-point draws gave daily Sharpes of 30–50. And one sweep audit line was logged after its run (line 63). The 3.14 s itself is shaky: its bootstrap 95 % CI is
2.23–3.22 s, because the official stamp has 1 s resolution, and at 2.23 s the 1 s cell makes only about $8 a day held
out (`results/redteam/stamp_lag.json`, `derived.json::cv.at_L_boot_lo.oos.usd`).
Evidence: `research/v2/tier0/PREREG.md`; `research/v2/tier0/DEVIATIONS.md` V3; `results/oos_peeks.log`.

**Q6. "The same inference read the other way loses. Why show only the reading that pays?"**
We show both. Applied as a constant 3.14 s lag over each tournament's points, it makes $94 / $57 a day. Applied
per point with the inferred 1.35 s bounce-to-reprice, it fills nothing correct at V = 1 and loses $17 a day; its
break-even is 0.34 s IS / 0.30 s OOS. The two disagree because the constant lag puts the simulated reprice at a
median of about 1.8 s after the bounce, later than the 1.35 s the inference itself implies. That disagreement is
exactly why we lead with the break-even and not with a P&L. The per-point loss is not a fluke: read per point, the
inference puts every reprice at most 1.78 s after the bounce, and a 1 s-feed order cannot arrive before 1.83 s even
with a 200 ms early call, so no correct call can fill (`results/redteam/stamp_lag.json::per_point_reading_V1`).
Evidence: `latency_sweep.json::video_own120.stamp_calibrated["1"]`, `breakeven_video_delay.stamp_calibrated`;
`results/tier0/results.json::timing`; `research/v2/latency/results.json::summary.m1.book_vs_official_T_s` (median
R −1.16 s).

**Q7. "Your video says the book reprices 0.7–1.3 s after the ball lands. A 1 s feed plus the 1 s hold gets your order
there at about 2.05 s. How do you make money?"**
On the median point you lose that race, and we say so. 0.68 s is the median under the pre-registered lag and
1.35 s is the per-point inference, and at either value a 1 s feed loses. Under the pre-registered reading the 1 s
order fills only when the book reprices after the umpire's stamp (R > 0; the pool's R has p90 +0.07 s, so about one
point in ten), which is why it breaks even. The post hoc 3.14 s lag pushes every reprice 1.14 s later, to a median
of about 1.8 s after the bounce, so the median point becomes winnable. That shift has not been measured. The video
line is being fixed to "0.7 to 2 seconds in our readings, not measured".
Evidence: `results/tier0/results.json::timing`; `latency_sweep.json::timing_diagnostics.R_cluster_just_above_threshold`;
`docs/video_script_v2.md` S02; Eq. (3) in the paper.

**Q8. "Isn't the 1 s headline just your courtside-camera counterfactual with a new label?"**
In the model, yes, and we say so. Only bounce-to-reprice time enters the race, so video(V, L) = video(V − (L − 2),
2). The 1 s feed at L = 3.0 s is exactly the camera at L = 2.0 s ($88.79 / $46.43 a day), and the L = 3.14 s cell
equals a camera 0.14 s ahead of the bounce. That is why the paper leads with the lag-free statement: the call
must beat the umpire's stamp by about 0.9 s.
Evidence: `latency_sweep.json::model.video`, `check_V0_equals_published_headline`; `LATENCY_SWEEP.md` §3.

**Q9. "The inference assumes the fast tier are courtside humans with a 0.25 s reaction. If they are machines, what
is your result?"**
Reaction time barely moves it, because the venue's 1 s hold anchors the inference. Bounce-to-reprice = 1 s hold +
reaction + network + 32 ms, so even a 20 ms bot in London gives L ≈ 2.85 s, which at V = 1 is about +$39 IS / +$30
OOS a day. That sits 0.15 s from a cliff where 50 ms costs a third of the P&L. What the inference really rests on
is that those prints react to the bounce at all, and on how the lag is applied: per point it loses at any
V ≥ 0.34 s. One live session timing bounce against stamp settles it.
Evidence: derived for this sheet, no new run (method in §5 below); `results/tier0/results.json::inputs.stamp_lag_calibration`;
`latency_sweep.json::timing_diagnostics`.

**Q10. "Your call model was trained and scored with a look-ahead feature. Causally, how good is it?"**
The live engine is causal; the offline evaluation was not, and our engine README documents the gap. The offline
`hb` feature was a median over the whole labelled flight, and the offline window kept deciding after a far-side
bounce. Streamed causally on held-out games, the engine called 4 of 41 test misses, all correct (95 % lower bound
51 %), median lead 162.5 ms. The offline figure was 11 of 11 at 50 ms. The hook clip's call is 325 ms causally, not
408 ms. The engine also fired 7 MISS calls on balls outside the scored set, 5 of them between rallies, and
nothing gates on rally state yet. With no early calls at all (the pessimistic CV), the pre-registered 1 s cell
makes $8 a day IS and loses $13 a day OOS. And the look-ahead does not drive the 1 s result: rerun with the live
engine's own call table, the 1 s cells are +$17 IS / +$3.81 held out pre-registered and +$98 / +$57.42 post hoc, against
+$15 / +$4.35 and +$94 / +$56.59 with the offline table (`results/redteam/causal_cv.json`; one logged burned-OOS read).
At a 1 s feed the race is decided by reprice timing, not by a 50–200 ms lead.
Evidence: `engine/README.md` ("Vision on one GPU", "Known gaps"); `results/engine/online_vs_offline.json`
(`A_engine_calls`, `calls`, `flights_called_or_miss` test_2/2819); `latency_sweep.json::video_cv_pessimistic`.

**Q11. "Sharpe 11.9 at 1 s, a failed v3 blind test, a losing replay. Which one is your strategy's performance?"**
The measured strategy is v2, at the fast tier's own fills: +0.60¢ [0.09, 1.13] out of sample, Sharpe 6.7, gone
once fees double. That measures the opportunity at their speed, not our execution. The CV strategy is a
simulation, and its pre-registered answer is break-even at a 1 s feed. Everything else is a bracket: post hoc +$57
a day, stamp-calibrated −$17, replay −0.92¢, and the tier-0 v3 rule failed all three blind sets (−0.22¢ and
−0.52¢ per share). We do not claim a bankable CV P&L.
Evidence: Table 1 and Table 2 sources in `docs/paper/PLAN.md` §7; `results/tier0_v3/blind.json`.

**Q12. "Forget Sharpe. After paying for the data, what do you make a year?"**
Gross at 1 s is $20.7k a year OOS post hoc and $1.6k pre-registered. After the cheapest quoted data licence plus a
London VPS ($42 a day) that is +$14 or −$38 a day, and at the central $5k-a-month quote it is −$110 or −$163 a
day. The book can afford at most $1,644 a month for data under the post hoc reading and $55 under the
pre-registered one, and the video licence it also needs has no public price. At today's 5 % fee COURTSIDE prices
speed. It is not yet a business, and the paper says that.
Evidence: `results/financials/financials.json::cost_assumptions`, `strategies.v2.cost.daily`; arithmetic in §5.

### Method and rigor

**Q13. "A Sharpe of 14.5 on daily data. The brief says above 3, assume a bug."**
We assumed one and found one: onset hindsight (D9). Fixing it cut IS Sharpe from 16.8 to 14.5. What remains is
about 270 small, near-independent binary bets a day with net exposure capped at 100 shares per match, so a high
Sharpe goes with tiny dollars ($196/day on $28k). It falls fast with costs: 9.8 at +½ tick, 3.0 with all costs
doubled, 6.7 OOS. The deflated Sharpe out of sample is 0.075 at N = 3,410, so 40 days cannot rule out luck.
Evidence: `results/v2/note_metrics.json`; `results/rigor/rigor.json`; `research/compliance/JUDGE.md` §5 Q3.

**Q14. "v2 fills at the fast tier's own print. Isn't that lookahead, and someone else's P&L?"**
It is their speed, and every v2 number is labelled "measured at the fast tier's own fills: the opportunity at their
speed, not our execution". Nothing in it uses the future: wallets qualify on past months only, the fee is the one
in force, and the window starts at detection, not at the onset seen afterwards. The executable lagged version,
copying 3 s later, loses in every month. That is the evidence that the edge is speed.
Evidence: `research/compliance/JUDGE.md` §5 Q1; `results/alpha/alpha.json::A_source`.

**Q15. "You built v2 after v1 lost $36k out of sample. Isn't v2 tuned on OOS?"**
v1 opened the OOS once, blind, and its −$36,056 is reported. v2's rules were set on in-sample data only, but its
motivation came from how v1 failed, so we call that window burned and label every v2 number on it non-blind.
v2's clean tests are the blind U2 test (OOS +1.22¢ [−0.19, 2.65], a fail by our rule) and the forward window, run
once on Oct 4 (Q23).
Evidence: `HYPOTHESIS_V2.md`; `results/expand/results.json`; `results/summary.json::oos.h6_shadow`.

**Q16. "What happens when costs double? What is your cost in bps?"**
Fees are each match's own rate × q(1−q): about 120 bps of notional IS and 179 bps OOS, and spreads are paid as
traded. Doubling fees keeps IS positive (+0.77¢, 7 of 7 months), but OOS turns negative: −0.34¢ [−0.86, 0.19],
0 of 3 months. All costs doubled gives −0.84¢ OOS. So in today's regime the edge does not survive doubled costs,
and venue rules are the first risk in §6.
Evidence: `results/v2/cost_stress.json`; `results/v2/note_metrics.json`.

**Q17. "With thousands of variants, isn't this the luckiest draw? Are your sweep cells counted?"**
Every strategy configuration is counted: 3,410 in the deflated Sharpe, which is 0.997 IS and 0.075 OOS, so the
OOS cannot rule out luck and we say so. The 18,880 sweep simulations are sensitivities that chose no rule, but
showing the 3.14 s reading as a headline was a choice made after looking, so it is listed as one more post hoc
trial. PBO is 0 % on the 55-policy sizing grid and 15 % on the v2-safe grid.
Evidence: `results/rigor/rigor.json::psr_dsr`, `pbo_cscv`; `latency_sweep.json::run`.

**Q18. "Who is the fast tier, and why hasn't competition killed the edge?"**
We can't name them, but we can describe them. They trade within 3 s of a point, qualify walk-forward, and on
11,307 never-examined markets beat everyone else by +3.09¢ IS and +2.16¢ OOS. Prints in the half-second before
a reprice are 98 % with the move, so someone knows the point about a second before the book does. Competition is
biting: the edge shrinks −0.20¢ a month (t = −4.0) while staying positive, and the move to a 1 s hold and 5 % fee
cut it from 1.64¢ to 0.54¢. That is what the structural-constraint story predicts.
Evidence: `results/alpha/alpha.json::headline.fast_tier_slope_c_per_month`; `results/expand/results.json`;
`research/v2/latency/results.json::summary.trades_around_reprice`.

**Q19. "What kills it?"**
In order of size: (1) the unmeasured stamp lag, which flips the CV sign; (2) our queue position against the fast
tier, where filling only 0.25 s ahead of the reprice roughly halves the edge; (3) fees, since doubling them erases
v2 OOS; (4) a longer venue hold; (5) concentration, with the top 5 wallets carrying 81 % of v2's IS P&L and 142 %
of its OOS P&L. Kill switches are in code: $1,000 daily stop, stale feed > 2 s, stale vision > 1 s, latency above
its rolling p95. Policy rules: halve size below a 0.3¢ trailing-30-day edge, stop at ≤ 0, and stop at a 5 %
drawdown.
Evidence: `docs/RISK.md`; `engine/risk/`; `research/v2/tier0/RESULTS.md` §3; `alpha.json::headline.top5_wallet_share_of_pnl`.

**Q20. "What failed?"**
Every blind test of a tradable book failed or is pending, while the speed mechanism held in every test. H1 (follow
the jump) lost. v1 lost $36k OOS. v2 on unseen markets failed OOS (CI spans zero). Maker v1 failed blind
(−$379). Tier-0 v3 failed all three blind sets. Table tennis is untestable: no wallet qualifies, 27 evaluable
matches, a median spread of 94¢. The replay loses. All of these are in Table 3, and we count them as evidence.
Evidence: `docs/paper/PLAN.md` §7 Table 3 sources; `results/tt/results.json`; `results/maker/oos.json`.

**Q21. "Is Polymarket allowed here? Isn't this courtsiding?"**
The track allows "any liquid, publicly traded market". Polymarket has a public order book, public data with no
keys, and $2.84B traded in our universe. *Cite the organizers' written confirmation if you have it.* We place no
orders and connected no funded account (Terms 5.3). The international venue is close-only for US persons, and a
deployment would need a permitted venue, licensed data and legal review. We do not courtside: the design is a
licensed feed, and a spectator camera for betting breaks ITF rules and ticket terms, which we cite.
Evidence: `research/compliance/REQUIREMENTS.md` G; `results/home_stream/sub_second_routes.json::compliance_flags`.

**Q22. "Your OOS is 20 % of matches but only about 40 days, and the volume filter is ex post. Isn't that
survivorship?"**
We read "20 % of history" as 20 % of observations: 2,617 of 13,084 matches and 21 % of volume. By calendar time it
is about 40 days, and the paper says which reading we used. The ≥ $5k volume filter is ex post, so we ran the
blind U2 test on 11,307 smaller markets, where the fast-tier gap holds and v2's OOS CI includes zero.
Evidence: `research/compliance/JUDGE.md` §5 Q8; `results/expand/results.json`.

**Q23. "Where is the forward test, and what did the live session do?"**
The forward window opened Oct 3 14:00 UTC and runs once, blind, at 11:30 UTC on Oct 4 (`HYPOTHESIS_V2.md`;
`scripts/forward_test.py` is sha-pinned). The live paper session (maker v1 plus a taker control, no real money)
quotes until 11:30 UTC.
→ **[if `results/v2/forward.json` exists]** "Forward: A ⟨…⟩¢ [lo, hi] PASS/FAIL, B ⟨…⟩¢ [lo, hi] PASS/FAIL, n = ⟨…⟩."
**[else]** "It runs once at 11:30 UTC; whatever it shows is reported."
→ live: **[if `results/live/FINAL`]** quote `summary.json::books.B1` **[else]** "quoting stopped 11:30 UTC, ⟨fills⟩ fills,
settlement pending". At 22:33 UTC on Oct 3 it was still in warm-up with 0 fills.

**Q24. "Can we run your code and get your numbers?"**
Yes: `bash run.sh setup`, `bash run.sh data`, `bash run.sh reproduce` regenerates the tables, and `bash run.sh replay`
replays the paper engine on recorded books in about 15 s with no network. Every number in the paper, deck and
video is read from a results file through a manifest. One gap: the frozen vision model (12 MB) is not
distributed yet, so CV calls cannot be regenerated from a clone (CLEAN_CLONE N6).
Evidence: `research/compliance/CLEAN_CLONE.md`; `results/viz/v2_assets/manifest.json`; `docs/deck/courtside_manifest.json`.

**Q25. "How many times did you look at the held-out data?"**
Every look is a line in `results/oos_peeks.log`: 68 lines as of 22:30 UTC Oct 3, classed in the paper's Table A6
as blind first runs, non-blind burned reads, descriptive reads, audits and replays. Rules changed after a look
twice: v2 itself and the D9 fix. We also flag one audit line that was logged after its run (line 63).
Evidence: `results/oos_peeks.log`; `DEVIATIONS.md`; `docs/paper/PLAN.md` §12.13.

---

## 4. Conditional lines (fill on the day, from files only)

| Item | File that unlocks it | Line when present | Line when absent |
|---|---|---|---|
| End-to-end timing | `results/e2e/summary.json` (present; other workflow) | Q1 bracket above, re-read before the talk | "Components measured; one-process end-to-end run in progress." |
| Capacity | `results/capacity/capacity.json` | "CV at 1 s: capacity ⟨$⟩ before the OOS CI spans zero; v2 ⟨$⟩." | Q2 as written |
| Ex-ante replay | INTEGRATION_TODO C1 output (replay workflow; an exploratory selective variant was logged 23:01 UTC) | Q4 extra line, labelled post hoc unless run under a PROTOCOL amendment | Q4 as written |
| Causal-CV cell | `results/redteam/causal_cv.json` (present) | Q10 line above | — |
| v2-safe forward | `results/v2/forward_safe.json` (`scripts/forward_test_safe.py`, run once after the pinned runs) | "v2-safe, reported not tested: ⟨c⟩¢ [lo, hi] full window; blind sub-window from 18:00 UTC ⟨c⟩¢" | "runs after the pinned forward test" |
| Forward test | `results/v2/forward.json` | Q23 filled | "runs once 11:30 UTC" |
| Tier-0 v3 forward | `results/tier0_v3/forward/results.json` | "frozen v3 forward: ⟨c⟩¢ [lo, hi] over ⟨n⟩ matches" | "pending" |
| Live session | `results/live/FINAL` | B1 fills and P&L | "settlement pending" |

---

## 5. Derived numbers used above (computed for this sheet; no new simulation, no new OOS read)

* **Most the book can pay for data**, $/day × 30.42 − $77 VPS (`financials.json::cost_assumptions.vps_london.central`):
  post hoc IS $2,793 / OOS **$1,644** a month; pre-registered IS $373 / OOS **$55**. Net per day at the low cost
  stack ($42.23): post hoc +$52 / +$14, pre-registered −$27 / −$38. At the central stack ($166.93): post hoc −$73 /
  −$110, pre-registered −$152 / −$163. Annualised gross (× 365): post hoc $34.4k / $20.7k, pre-registered $5.4k / $1.6k.
* **Stamp lag needed at V = 1 s** (tournament reading, model identity applied to the dense L = 2.0 grid in
  `results/tier0/latency_sweep.csv`): break-even L ≥ 1.91 s IS / 1.99 s OOS; covering the $42/day low cost stack
  needs L ≥ 2.87 s IS / 2.98 s OOS; the $167/day central stack is not covered even at L = 3.14 s.
* **Reaction-time sensitivity of the inference.** `calibrate_stamp_lag` is linear in its two assumptions:
  L = 3.142 + (reaction − 0.25) + (network − 0.067) s, which reproduces all nine grid rows in
  `results/tier0/results.json::inputs.stamp_lag_calibration`. A 20 ms bot in London (2 ms) gives L = 2.85 s. By
  the identity, V = 1 at L = 2.85 equals V = 0.15 at L = 2.0: about +$39/day IS (Sharpe 5.4) and +$30/day OOS
  (Sharpe 4.5), interpolated on the 0.05 s grid. Reaction 0.10 s with a 67 ms network gives L = 2.99 s and about
  +$84 / +$45. These are existing sweep cells read through the model identity, so treat them as model
  statements, not new evidence.

---

## 6. Red-team additions (Oct 3, about 23:45 UTC): three more questions

**Q26. "Your 3.14 s lag is a median of 49 points with a 1-second clock. How tight is it?"**
Not tight, and we say so. Its bootstrap 95 % CI is 2.23–3.22 s, a third of resamples fall below 2.5 s, and a narrower
print window gives 2.23 s. The official stamp has 1 s resolution, so per-point lags cluster a second apart. At 2.23 s
the 1 s cell makes about $8 a day held out, less than the cheapest data stack. That is why the pre-registered 2.0 s
reading leads, and why the next step is one session that times bounce against stamp.
Evidence: `results/redteam/stamp_lag.json::bootstrap`, `windows`; `results/redteam/derived.json::cv.at_L_boot_lo.oos.usd`.

**Q27. "What stops your engine trading a miss call between points?"**
Nothing yet, and it matters. On 14 minutes of held-out video the live engine made 7 miss calls on balls outside the
scored flights, 5 of them between rallies: about 30 an hour. Each phantom trade costs about $1.75 at 100 shares (fee
plus half spread), so the post hoc 1 s P&L survives only about 32 a day and the pre-registered one about 2. A
rally-state gate (a miss counts only within 2 s of a bounce call on the same match) is now in the strategy code
(`StrategyConfig.rally_gate_s`, with tests), off by default so the committed runs reproduce, and not yet evaluated on
the full event log. For tennis it needs a serve detector, which we have not built. No live trade happens without it.
Evidence: `results/engine/online_vs_offline.json::runs.fp16_cl_fuse_compile_b1_realtime.calls.unmatched`;
`results/redteam/derived.json::eng.phantom_*`; `research/compliance/INTEGRATION_TODO.md` §8 R-3.

**Q28. "Does Polymarket really hold every order exactly 1 s?"**
Not exactly, as far as we can tell. 35 % of book reprices and 65 % of the first informed prints land within 100 ms after
a whole UTC second, against 10 % if timing were uniform. That looks like delayed orders being released on a 1 s clock.
Our simulation treats the hold as a continuous 1.000 s. If release is batched with time priority the race is unchanged;
if priority inside a batch is not by send time, the model is conservative for us. We have not measured which.
Evidence: `results/redteam/stamp_lag.json::whole_second_clock`; `results/tier0/latency_sweep.json::timing_diagnostics`.
