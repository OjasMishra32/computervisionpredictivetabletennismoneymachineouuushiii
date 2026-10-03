# Backtest example match: selection rule

> **Example match from the backtest (selected for illustration) · simulated 1 s licensed-feed baseline · real
> Polymarket price path · paper.** Share of backtest matches that were profitable at this setting: computed by
> the run and appended below the rule (the rule was committed before any per-match P&L was computed).

Written 2026-10-03T23:03:47Z, before any per-match P&L was computed. Nothing below was chosen after looking at
match-level results. The per-seed totals used for the seed choice are the sweep's published seed-level
numbers (`results/tier0/latency_sweep_seeds.csv`), not match-level numbers.

## Rule (as given)

reading = calibrated (tournament_lagcal), V = 1.0 s, seed = the median seed by total P&L; among matches with
>= 6 trades and positive P&L, take the one with the most trades; ties by earliest start; also report the share
of all traded matches that were profitable (IS and OOS) and the median match P&L.

## Exact definitions

* **Cell.** `scripts/tier0_latency_sweep.py` cell `("video", "tournament_lagcal", 1.0, "own120", period, seed)`:
  the revised primary tier-0 model (`src/tier0.py` `CORRECTED`), video + our CV delayed by V = 1.0 s, reprice
  timing R drawn once per tournament, stamp lag = the calibrated 3.14 s (an inference, chosen post hoc in the
  sweep, not pre-registered; the pre-registered lag is 2.0 s). Both periods: IS and burned OOS (not blind).
  The sweep code is imported and called unchanged; nothing is edited or refitted.
* **Seed.** The sweep's 20 seed indices s = 0..19 (IS draws use seed s, burned OOS seed 1000 + s). Total P&L of
  seed s = IS `pnl_usd` + burned-OOS `pnl_usd` of that cell. Seeds are ranked by total ascending (ties: lower
  index). With 20 seeds there is no single middle seed, so the **median seed is rank 10 of 20 (the lower
  median)**. The rerun must reproduce the sweep's per-seed `pnl_usd` for the chosen seed (checked in the
  output).
* **Match.** One Polymarket tennis moneyline market (condition id) in the period.
* **Trade.** A call whose order fills: `shares > 1e-9` after the per-match net cap (the definition of `n_trades`
  in `T.metrics`). A call whose order does not fill is a **miss**.
* **Traded match.** A match with at least one trade.
* **Match P&L.** Sum over the match's trades of shares x (payout − fill price − fee per share), USD, at the
  model's sizes ($1,000 per order cap, 100-share net cap). Profitable = match P&L > 0.
* **Eligible.** Traded match with >= 6 trades and match P&L > 0. IS and burned OOS pooled.
* **Choice.** The eligible match with the most trades. Ties: earliest scheduled start (universe `start`), then
  the lower condition id (string order).
* **Also reported (at the chosen seed).** Share of traded matches with P&L > 0 and the median match P&L, for IS,
  burned OOS and pooled. Supplementary, not used for the choice: the same two numbers for every one of the 20
  seeds.

## Saved

`match.json` in this directory: the chosen match's real price path (every Polymarket print of the in-play tape
used by the backtest: time, outcome-0 price, USD size), every model call with its order, fill or miss (times
relative to the modelled ball landing, the historical jump onset on the real clock, fill price, shares, fee,
payout), P&L per trade and cumulative, and the profitable-share statistics.

## Outcome (appended after the run; the rule above is unchanged since commit e71d62e)

> **Example match from the backtest (selected for illustration) · simulated 1 s licensed-feed baseline · real
> Polymarket price path · paper · 548 of 931 traded backtest matches (58.9%) were profitable at this setting
> (IS 60.9%, burned OOS 52.2%; seed 14).**

Run by `scripts/backtest_example_match.py`. The rerun reproduces the sweep's `pnl_usd` for all 20 seeds in
both periods (`results/tier0/latency_sweep_seeds.csv`), and the per-call timing it reports equals the tau
`T.simulate` returns.

* **Seed.** Index 14: rank 10 of 20 by total P&L ($12,541.28 = IS $11,813.22 + burned OOS $728.06).
* **Match.** Iasi Open (WTA, in sample): Anna Bondar vs Tamara Zidansek, 2026-07-15 12:30 UTC, won by Zidansek
  (`wta-bondar-zidanse-2026-07-15`, condition `0x2520d8a1…245d`). 107 calls: 62 fills (58 correct, 4 wrong) and
  45 misses (42 blocked by the 100-share net cap, 3 with no stale depth left). Match P&L **+$82.22** (+0.89c per
  share on 9,238 shares, $4,487 in), at settlement. 32 of the 62 trades made money; the best made +$138.92 and
  the worst lost −$144.85. Of the 290 eligible matches (>= 6 trades, P&L > 0) it has the most trades, so no
  tie-break was needed. The runner-up is an IS match with 59 trades and +$82.10.
* **Not typical.** It was picked for its trade count among profitable matches. At seed 14 the median traded
  match made **$11.27** (IS $13.44, burned OOS $5.34), and **58.9%** of traded matches were profitable (IS
  432/709 = 60.9%, burned OOS 116/222 = 52.2%). Across all 20 seeds the pooled share ranges from 52.5% to 64.6%
  (mean 59.8%); this is supplementary and was not used for the choice.
* **Why it trades so often.** Reprice timing is drawn once per tournament. In this tournament's draw the book
  reprices 2.29 s after the ball lands, so a call on the 1 s-delayed video reaches the book about 0.26 s
  before the reprice. Every correct call in this match arrived in time; none missed for being late.
