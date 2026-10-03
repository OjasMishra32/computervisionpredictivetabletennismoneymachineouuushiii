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
