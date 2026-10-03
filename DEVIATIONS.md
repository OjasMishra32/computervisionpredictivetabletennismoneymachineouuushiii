# Deviations from HYPOTHESIS.md

Every change after the pre-registration commit (7232986, 2026-10-03 09:50 UTC), with the reason.
Out-of-sample matches (start >= 2026-08-25 14:15 UTC, the last 20%) have not been opened for any
of the analysis below.

## D1 — execution model (before any result)
- Entry delay uses each match's own `secondsDelay` (3 s before ~mid-2026, 1 s after) + 1 s of our
  latency, not a flat 2 s. The pre-registration assumed today's 1 s for every match.
- Instead of "half the median live spread", fills use real prints on the side of the book we
  would hit (an outcome-0 buy needs a print that lifted outcome 0's ask). Spread is paid as
  historically observed.
- Fees: each match's own `feeSchedule.rate` (0, 0.03 or 0.05) × p(1−p) per share per leg.
- H2 "during play" is operationalised as the first in-play entry into the band from below (the
  favourite was < `lo` earlier in play), so static pre-match favourites are not counted.

## D2 — H1 fails in sample; tier analysis added (after viewing IS results)
- H1 (follow the jump) on the first 600 IS matches: −1.47¢/share, 95% CI [−1.80, −1.13], hit
  rate 38%, in a zero-fee period. The pre-registered failure condition is met. H1 is reported as
  failed and has not been re-tuned.
- Added an exploratory markout study (`src/tiers.py`): every taker print bucketed by seconds
  since the latest jump onset. In sample, takers lose in every bucket. The spread triples in the
  first 3 s after a jump. Prints 6–40 s after a jump lose 0.5–1.0¢/share in both directions.

## D3 — new hypothesis H5, formulated AFTER seeing in-sample tier markouts
**H5 — post-event liquidity provision.** Taker delay protects makers from the fast tiers. Slow
tiers keep arriving for tens of seconds after a point, so a maker who quotes into the window right
after a detected jump earns more per share than one quoting at random times.
- Signal: the H1 jump detector (|Δ| ≥ J, J = 0.04), known in real time from prints only.
- Quote both sides at the touch from detection + 1 s to detection + W (W = 30 s primary).
- Fill: share φ = 0.2 of each taker print in the window, capped at $250 per print and $2,000 of
  gross inventory per match. Hold to resolution, so there is no unwind cost and no mark-to-model.
- Earn 15% of the taker fee on our fills (the sports maker rebate).
- Baseline: the same maker quoting through the whole match (every print).
- Variant budget: J ∈ {0.02, 0.03, 0.04, 0.06} × W ∈ {10, 20, 30, 60} = 16, all reported.
- **Fails if** the window maker's mean P&L per share ≤ the always-on maker's, or ≤ 0 OOS.
- Because H5 was written after looking at in-sample data, only its OOS result counts as a test.

## D4 — H5 fails in sample; fast-tier wallet study added (after viewing IS results)
- H5 in sample (3,490 matches, hold to resolution): window maker +0.40¢/share (CI −0.07…0.87),
  always-on maker +0.41¢ (CI 0.04…0.78). The window is not better: H5 fails its stated condition.
- H2 calibration in sample: realised win rate is within ±1.6¢ of price in every band 0.5–0.99,
  and every CI includes 0. H2's edge does not exist; H2 is reported as failed.
- Exploratory: wallet-level markouts in the 0–3 s post-jump bucket. 390 wallets with ≥30 such
  prints over ≥10 matches. The top wallets earn +2–3¢/share at 30 s with t-stats of 10–23.
  Split-half (odd/even match id) correlation of wallet markout is 0.50. Top 16 (t > 3) = 24.8% of
  IS taker USD.

## D5 — H6, formulated AFTER D4 (only its walk-forward / OOS result counts as a test)
**H6 — the fast tier is persistent and its edge is the size of the prize for a tier-0 trader.**
Wallets selected as fast-tier using only data before month m keep positive net-of-fee markouts on
their 0–3 s post-jump prints in month m, and in the locked OOS period.
- Selection (walk-forward, monthly): ≥30 prints in the 0–3 s bucket over ≥10 matches before m,
  t-stat of mean 30 s markout > 3.
- Metric: their month-m prints in that bucket, net of each match's taker fee: mean markout at
  30 s and to resolution, clustered by match.
- Follow test: a copier entering at +delay+3 s (venue delay, our latency, on-chain indexing).
- **Fails if** month-m net markout ≤ 0 in more than a third of months, or ≤ 0 OOS.

## D6 — shadow-book accounting and OOS freeze (before opening OOS)
- Shadow book: size per trade = min(wallet's own print, $1,000); at most $3,000 committed per
  match; held to resolution; net of each match's taker fee. Capital = 3× the peak dollars locked in
  open positions (the first version used a flat $50k and overstated the drawdown denominator's
  relevance; fixed before OOS).
- In-sample, by venue regime, net-to-resolution edge per share: 3 s/no fee 1.51¢; 3 s/3% 1.64¢;
  1 s/3% 1.19¢; 1 s/5% 0.54¢. OOS is entirely 1 s/5%, so the relevant IS comparator is 0.54¢.
- H5 in sample (full IS): primary J=0.04/W=30 +0.22¢ (CI −0.01…0.43) vs always-on +0.13¢ (CI
  −0.06…0.32). That passes the stated IS condition on the point estimate only.
- Frozen for OOS: H1 J0.04/H30, H2 0.85–0.97, H5 J0.04/W30 + always-on, H6 selection rule and
  shadow sizing as above. OOS is evaluated once via `run_all.py --oos`; peeks are logged in
  `results/oos_peeks.log`.

## D7 — after the single OOS evaluation (2026-10-03 10:42 UTC)
- OOS results are reported as computed; no rule was changed afterwards.
- Post-OOS diagnostics only (decompositions, `scripts/diagnostics.py`): shadow-book dollar P&L by
  entry price, and always-on maker P&L by venue regime. They explain results; they are not used to
  pick or re-fit anything.
- Figure fix after OOS: the walk-forward figure now plots the same capped shadow book the stats use
  (it plotted the uncapped one) and colours OOS months. Numbers are unchanged.

## H3 — ball tracking / early call (all decided on game_1..5 before test_1..7 was evaluated)
Test videos were run through the detector and tracker, which use no labels. Their labels were read once,
by `early_call.py --final` (logged in `results/tracking/test_peeks.log`).

- **H3-D1. What "net" means in OpenTTGames.** The `net` event marks the frame where the ball reaches the net
  plane, on every shot. It is not only a net touch. Evidence: game_1..5 have 1,232 `net` and 1,537 `bounce`
  events, and 92% of `net` events are followed by a far-side bounce 8–50 frames later. So "miss (out / net)"
  is not labelled and has to be inferred. One flight = one shot reaching the net plane, anchored at its `net`
  frame. **BOUNCE** = a far-side `bounce` follows within 0.5 s. **MISS** = it does not (the next event is at
  least 80 frames later, i.e. the next rally, or the ball came back). MISS/net = the ball stops at the net:
  it never gets 25 px past the crossing, or its along-table speed drops below 40%. MISS/out = everything else.
  Shots that never reach the net plane (mis-hits into the ceiling or the floor) and the serve's own-side bounce
  are not in the sample. The rule was checked visually on all 14 game_1 misses and on a random sample of 9 training misses; all were
  consistent (`results/tracking/miss_spotcheck.png`).
- **H3-D2. Which call is scored.** "Precision" means the precision of **MISS** calls, which are the
  point-ending, tradeable calls. About 90% of shots land, so a BOUNCE call is trivially more than 90%
  precise and says nothing.
- **H3-D3. Reference time for misses.** For a net miss, T_ref = the net frame. For an out ball, T_ref = the
  first frame the tracked ball passes the table end line (mean x of the two end corners), drops below the near
  edge, or is lost. This comes before the ball reaches table-plane height, so the measured leads are
  conservative (shorter).
- **H3-D4. Call rules.** The verdict uses the literal "precision at a 50 ms lead". The decision is made at
  frame T_ref − 6 (the **snapshot rule**), using only track points up to that frame minus 2 frames, because
  the detector's 3-frame window looks 2 frames ahead. We also report an **online first-call rule**: a call
  counts once the score has stayed ≥ τ for 3 consecutive frames, and the trading half's "tier-0 lead" is
  taken from this rule. Calls are only allowed when the ball is predicted to reach the net or the end line
  within GATE_H. Longer single-camera extrapolations produced most of the early false alarms in the training
  games. GATE_H was chosen by leave-one-game-out CV on game_1..5 from {∞, 0.25, 0.15, 0.10} s.
- **H3-D5. Model and threshold (frozen before the test run).** Three candidates × four gates were compared
  by leave-one-game-out (LOGO) CV on game_1..5 (1,059 BOUNCE / 110 MISS flights): a physics logistic regression
  (8 features: landing position relative to the end line at the far, mid and near table level; arc height at
  the net and at the end line; time to the end line; net passed; no landing predicted), a logistic regression
  on all 23 features, and sklearn gradient boosting (HGB) on all 23 features. τ is the smallest threshold at
  which the out-of-fold train precision at the 50 ms lead is ≥ 95% and stays ≥ 95% for every higher threshold
  with ≥ 5 calls. It is set separately for the snapshot rule (verdict) and the online rule (first-call leads).
  Selection criterion: the largest sum of snapshot and online recall at 50 ms, among candidates with both
  precisions ≥ 95%. We fixed this criterion after seeing the train CV table, because the best snapshot model
  (physics LR) has almost no online recall. The winner is **HGB with GATE_H = 0.10 s**: OOF snapshot@50 ms
  precision 0.952, recall 0.545 (60/63 calls); OOF online@50 ms precision 0.971, recall 0.30 (33/34). Physics
  LR without a gate had snapshot recall 0.555 at precision 0.953 but online recall 0.05–0.06. All of these
  numbers are from `work/tracking/dev_report.json` on HiPerGator (copied to
  `results/tracking/dev_report.json`). The HPG and laptop runs agree to within a few calls (sklearn versions
  differ).
- **H3-D6. Detector.** At the user's direction we reused the pretrained BlurBall table-tennis detector (MIT
  licence, built on WASB-SBDT) zero-shot instead of training a tracker. BlurBall beat the WASB weights on
  game_1/game_2 labels and was the only detector run on all videos. Frames are processed only inside annotated
  rallies, from 1.5 s before the first event to 2.5 s after the last: 273k of 644k frames.
- **H3-D7. Units.** There is one camera, so speeds (m/s) and "how far out" (m) are image estimates scaled by
  the table length (2.74 m). Depth across the table is not observable, and the true bounce level lies between
  the far- and near-edge lines. This ambiguity (about 0.1 table length of image height) is the main physical
  limit on early calls.
- **H3-D8. Which annotations the test pipeline reads.** For each test video the pipeline reads three
  annotation sources. (a) The table quadrilateral comes from its segmentation masks; a deployed system would
  get the same thing from a one-off camera calibration. (b) The frames processed are the annotated rallies.
  (c) The shots evaluated are anchored at their `net` events, and their outcome is labelled from the events
  (rules in H3-D1). The prediction itself uses only the tracked ball positions. The flight start (racket hit
  or bounce) is found in the track without labels.
- **H3-D9. Scope.** The tennis Monte Carlo version of H3 is not part of this analysis.
- **H3-D10. POST-HOC, after the single test evaluation (2026-10-03 10:57 UTC): the test labels are incomplete.**
  The pre-specified run gave test precision 11/11 at 50 ms → PASS. We then visually audited those 11 calls
  (`results/tracking/test_called_audit.png`) and found that some test flights labelled MISS actually bounce on
  the far half of the table. The test markup has no `bounce` event for them, and the rally goes on.
  In the test set, 18 of 41 MISS flights are followed by another annotated event within 80 frames. The training
  games have 2 of 110. `src/tracking/audit_labels.py` finds such bounces from the track: a local maximum of
  image y inside the table quadrilateral, grown by one ball radius + 5 px, beyond the net. A first version used
  a 5 px margin and missed a far-edge bounce. The detector reports the ball centre, so the margin was changed
  to one ball radius. Both versions are post-hoc. The audit relabels 20 of 41 test MISS flights as BOUNCE and
  0 of 110 in training. Re-scoring the **frozen** model (no refit, same τ) on the corrected labels gives
  precision 8/8 at 50 ms (recall 0.38). If the 5 unresolved "rally continues" flights are also dropped, it gives
  7/7. The verdict is the same under every labelling, but with 7–11 calls the 95% Wilson lower bound is only
  0.68–0.74. `results/tracking/label_audit.json` has the numbers. The pre-specified result is still the one of
  record.

## D8 — v2 optimisation round (2026-10-03, after the single OOS run)
- Six optimisation lenses ran on IS data only (research/v2/*), each checked by two adversarial
  verifiers. Kept: risk-parity sizing + fee-aware wallet filter + 100-share net cap per match, held to
  resolution (sizing lens; verified, reproduced twice). Refuted: maker exits (wrong tick, and live data
  shows adverse selection). Too small: side-market leaning maker (~$2k/month). Not deployable
  remotely: Kalshi→Polymarket laggard (Kalshi leads ~69% of repricings, but the real lead is ~1.6–2 s
  once Polymarket's ~2 s block-time lag is removed). Latency audit: no public score source beats the
  book.
- v2 is frozen in HYPOTHESIS_V2.md and tested blind on a forward window starting 2026-10-03 13:00 UTC.
  The burned OOS figure for v2 is reported as non-blind.

## D9 — onset hindsight fixed; v2 made causal (before the forward run)
- Verifiers (research/v2/verify_v2/): the v2 code reproduces exactly, but the opportunity set used
  hindsight. Burned-OOS v2 fell from +0.75¢ to +0.60¢ [0.09, 1.13] with a causal window. With +½ tick
  slippage it is +0.10¢; with +1 tick, −0.40¢. In sample, causal v2 is +1.38¢ [1.17, 1.59], Sharpe
  14.5, 7/7 months, and still +0.38¢ at +1 tick.
- H1–H6 tables keep the onset-aligned labelling. They are an ex-post event study (who traded around
  score events), not a tradable set. Every tradable claim (v2) now uses the causal window.
- Forward-test changes are listed in HYPOTHESIS_V2.md amendment A1.

## D10 — corrections found while building the deck (2026-10-03)
- D4 said every calibration CI includes 0. That was true on the early partial sample. On the full
  in-sample set, 3 of 11 price bands have CIs that exclude the price, each by under ~1¢; the largest
  gap is 1.01¢. "Calibrated within ~1¢" stands; "every CI includes 0" does not.
- The out-of-sample period was opened once for v1 (10:42 UTC). v2 was then shown on it twice
  (onset 13:24, causal 13:53), labelled non-blind. All three are in results/oos_peeks.log.
