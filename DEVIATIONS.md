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
