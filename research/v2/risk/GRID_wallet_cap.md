# v2 per-wallet cap: grid and selection rule, declared before any variant is computed

Written 2026-10-04 ~05:30 UTC on top of de44cb7. No variant below has been run on any data yet.

## Why
The judges' note: the top 5 of 86 copied wallets carry 142% of v2's burned-OOS P&L, and without
them OOS v2 earns -0.34¢/share (`results/alpha/alpha.json::F_concentration`), yet v2 has no
per-wallet limit. We add one, chosen on in-sample data only, and then test it once on the burned OOS.

## What we had seen before writing this
- The frozen v2 (`G_50pct_net100`, causal) results already in the repo, IS and burned OOS,
  including the OOS concentration numbers above. **So the burned OOS is non-blind for this rule:
  the rule exists because of what the OOS showed.** Its OOS result will be labelled that way.
- One IS-only look at the frozen v2 book, to set the grid's range (no variant run): gross dollars
  per (copied wallet, UTC day) have median $159, p90 $1,510, p99 $3,890, max $7,591 over 2,860
  wallet-days; the book's daily gross has median $7,032; the largest wallet takes 19.5% of IS gross.
- Nothing from `data/locked/`, `data/expand_*`, `data/v2_lowloss/*_u1*` or
  `data/v2_trades_is_oos.parquet` is read for anything in this file.

## Data: IS only
- `data/v2_lowloss/features_is.parquet` + `whist_is.parquet`: the cached IS-only causal v2 feature
  table and wallet history built by `scripts/lowloss_select.py` from `data/is_prints.parquet`
  (matches starting before 2026-08-25 14:15 UTC). Every variant runs through the verified
  `research/v2/sizing/engine.py` (`month_targets` -> `apply_caps`), hold to resolution, actual fees.
- Sanity check before any variant is looked at: the baseline must reproduce
  `results/v2/causal.json::causal/is_eval/slip0.0` (55,662 trades, $40,425.72). Otherwise stop.
- Evaluation months 2026-02 to 2026-08; Sharpe calendar 2026-02-01 to 2026-08-25, zero-filled (as
  `scripts/rigor_pack.py`).

## The two levers
1. **Per-wallet daily exposure cap `W`** (engine `Policy.wallet_day_cap`, already in
   `apply_caps`): the gross dollars we spend copying one wallet in one UTC day may not exceed `W`.
   A trade that would cross it is cut to the remaining room; after that the wallet is skipped for
   the rest of the day. Because every v2 position is a token bought and held to resolution, the
   most one copied wallet can cost us in a day is `W` plus fees (fee <= 4.75% of dollars at a 5%
   rate). Grid: `W` in {inf, $4,000, $2,000, $1,000, $500, $250}.
2. **Wallet retirement on trailing edge `R`** (on/off). At each opportunity (wallet w, time t), take
   all of w's rows in the feature table (its walk-forward-qualified causal 0-3 s prints, every price
   and filter outcome) with timestamp in [t - 30 days, t - 30 s] and a 30 s markout. If there are at
   least 50 and their mean net 30 s markout (gross30 - rate*q*(1-q), per print) is <= 0, w is
   retired: target 0, no new copies. It comes back as soon as the same number turns positive.
   Positions already held are kept to resolution. Fewer than 50 rows: not retired (the frozen
   monthly wallet filter still applies).

Everything else is the frozen v2: `src.v2.POLICY` with `wallet_day_cap=W`, plus the retirement mask
on the targets when `R` is on. Grid: 6 x 2 = 12 variants; the baseline (`W` = inf, `R` off) is v2.

## Selection rule (IS, Feb-Aug 2026)
1. **Cap.** Among the `R` = off variants, `W` is feasible if its IS $ P&L >= 50% of the baseline's
   AND its IS per-share net edge has a match-clustered 95% CI (engine.metrics: 1,000 draws, seed 0)
   with lower bound > 0. Choose the **smallest feasible `W`** (the tightest cap that keeps at least
   half the dollars). If no finite `W` is feasible, `W` = inf.
2. **Retirement.** At the chosen `W`, switch `R` on only if, on IS, it raises **both** the
   per-share net edge and the calendar-day Sharpe versus `R` off. Otherwise `R` is off.
3. The pair (`W`, `R`) is frozen in `PREREG_wallet_cap.md`, which is committed before any OOS read.

The 50% threshold copies the feasibility bar of the v2-safe grid (`research/v2/lowloss/GRID.md`).

**Stability check (descriptive only, not a selection input):** the same rule applied on expanding
IS histories Feb-Apr, Feb-May, Feb-Jun and Feb-Jul; we report what it would have picked.

## IS metrics reported for every variant
Trades, matches, wallets; $ P&L; per-share net (¢) with match-clustered 95% CI; calendar-day Sharpe
(x sqrt(365)); max drawdown $ and worst day $; top-1 / top-5 copied-wallet share of P&L (as
`scripts/alpha_pack.py`: sum of the top-k wallets' P&L / book P&L, wallets ranked by P&L in the
same period); per-share net without the top-5 wallets; largest single wallet's share of gross
dollars; share of opportunity dollars blocked by the cap and by retirement.
