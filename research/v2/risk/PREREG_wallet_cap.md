# v2 per-wallet cap: frozen rule and the one burned-OOS test, pre-registered

Written 2026-10-04 ~05:40 UTC. The grid and selection rule were committed first, in
`GRID_wallet_cap.md` (f35131a, sha256 865604…aa1c), before any variant was run. The IS grid was then
run by `scripts/v2_wallet_cap.py --is` (output `results/v2/risk/wallet_cap_is.json`). This file, the
script with the frozen values, and the IS output are committed together **before any OOS data is
read for this rule**. The git timestamp of that commit is the pre-registration.

## What has been looked at
- **For this rule:** IS only (`data/v2_lowloss/features_is.parquet`, `whist_is.parquet`, built from
  `data/is_prints.parquet`). No burned-OOS print, trade or P&L was loaded for any variant. The OOS
  code path was dry-run on IS data only (fake "OOS" = IS matches starting in August).
- **Before the rule existed:** the frozen v2's burned-OOS results, including its concentration (top
  5 of 86 wallets = 142% of OOS P&L, -0.34¢/share without them). **The burned OOS is therefore
  non-blind: this rule was designed because of that result.** Every OOS number below carries that
  label.

## The frozen rule
**v2-wcap = frozen v2 (HYPOTHESIS_V2.md incl. A1, `src/v2.py`, causal) plus two limits:**
1. **Per-wallet daily cap W = $1,000.** The gross dollars spent copying one wallet in one UTC day
   may not exceed $1,000 (engine `Policy.wallet_day_cap`). A trade that would cross it is cut to the
   room left; then the wallet is skipped until 00:00 UTC. Since every position is a token bought and
   held to resolution, **one copied wallet can cost us at most $1,000 plus fees (<= $47.50) a day.**
2. **Wallet retirement on trailing edge (on).** At each opportunity, take the wallet's rows in the
   feature table from the last 30 days, each at least 30 s old (so its 30 s markout is known). If
   there are >= 50 and their mean net 30 s markout (gross30 - rate*q*(1-q)) is <= 0, the wallet is
   retired: no new copies until that number turns positive again. Open positions are kept.

Everything else is unchanged: walk-forward fast-tier qualification, fee-aware monthly wallet filter,
risk-parity size (deploy_frac 0.5), zone 0.05-0.95, $1,000 per order, $3,000 gross per match, 100
shares net per match, 4 h ex-ante capital lock, no daily stop in the backtest, hold to resolution.
In code: `FROZEN_W = 1000.0`, `FROZEN_R = True` in `scripts/v2_wallet_cap.py`; variant `W1000_Ron`.

## How it was chosen (GRID rule, IS Feb-Aug 2026)
- Feasible caps (R off; IS $ P&L >= 50% of v2's $40,426 and per-share CI lower bound > 0): $4,000,
  $2,000, $1,000. $500 ($17,210) and $250 ($13,845) keep less than half the dollars. **Smallest
  feasible: W = $1,000.**
- At W = $1,000, retirement raises per-share net (1.349¢ vs 1.247¢) and Sharpe (10.57 vs 10.32), so
  it is on.
- Stability (descriptive): on histories Feb-Apr and Feb-May the same rule picks W = $2,000 with
  retirement; on Feb-Jun and Feb-Jul it picks W = $1,000 with retirement.

## IS results (IS-only run, 2026-02-01 to 2026-08-25, causal, hold to resolution)
| | frozen v2 (no cap) | v2-wcap (W1000, retire on) |
|---|---|---|
| trades / matches / wallets | 55,662 / 7,639 / 80 | 38,703 / 6,999 / 80 |
| $ P&L | $40,426 | $25,462 (63%) |
| per-share net, match-clustered 95% CI | 1.381¢ [1.168, 1.594] | 1.349¢ [1.046, 1.652] |
| same, wallet-clustered 95% CI | [0.580, 2.286] | [0.286, 2.498] |
| Sharpe (calendar days, x sqrt 365), stationary-bootstrap 95% CI | 14.48 [11.93, 17.37] | 10.57 [7.54, 13.90] |
| max drawdown / worst day | -$569 / -$551 | -$1,212 / -$710 |
| top-1 / top-5 wallet share of P&L | 41.7% / 81.4% | 33.3% / 87.3% |
| per-share net without the top 5 wallets | 0.611¢ [0.005, 1.270] | 0.278¢ [-0.291, 0.813] |
| largest wallet's share of gross $ | 19.5% | 17.1% |
| worst single wallet-day P&L | -$925 | -$689 |
| capital (3 x peak locked) | $28,302 | $20,318 |

**Reading, written before the OOS run.** In sample the cap does what a loss limit does and no more:
no wallet can lose more than $1,000 a day (worst wallet-day -$689 vs -$925), and the largest wallet's
share of our dollars falls from 19.5% to 17.1%. It does **not** reduce P&L concentration: the top 5
wallets' share of P&L rises from 81% to 87%, because the cap also cuts profitable busy days of the
other wallets (their per-share net falls from 0.61¢ to 0.28¢). It costs 37% of the dollars and about a
quarter of the Sharpe, and it doubles the max drawdown. We expect the same on the OOS.

## Per-match loss under the stated limits (IS, frozen v2)
The paper says one match can lose at most $95 plus fees (100 shares net x 95¢). In sample:
- worst match -$205.76; p99 match loss $86.62; 49 of 7,639 matches (0.64%) lost more than $95;
- 79% of matches buy both tokens at some point, and 90% of loss dollars come from those matches. The
  net cap limits the open position, not the loss: buying one side and later the other locks in a loss
  while the net stays within 100 shares (risk-reducing trades are always allowed);
- worst day -$551; the $1,000 daily stop (engine semantics) never fires;
- the backtest's own $3,000 gross-per-match cap bounds one match at $1,471 + $7.50 fees (buy both
  tokens at 95¢ up to $3,000 with |net| <= 100). The live engine's RiskConfig has no gross-per-match
  cap, so there the per-match limits give no bound at all.

## The OOS test (run once)
- **Data:** `data/v2_lowloss/features_u1.parquet` + `whist_u1.parquet`, the joint IS + burned-OOS
  build of `scripts/lowloss_test.py` (hash-checked against `data/is_prints.parquet` and
  `data/locked/oos_prints.parquet`). One joint walk-forward run, so caps and retirement carry across
  the IS/OOS boundary as they would live. Gate: the frozen v2 from this build must equal
  `data/v2_trades_is_oos.parquet` exactly, or the run stops.
- **Books:** burned OOS = matches with `src.tape.universe().oos` (start >= 2026-08-25 14:15 UTC),
  Sharpe calendar 2026-08-25 to 2026-10-03. The IS part of the same joint run is also reported.
- **Logging:** `scripts/v2_wallet_cap.py --oos` appends one line to `results/oos_peeks.log` before it
  reads any OOS file, and refuses a second run (`--repro` only recomputes, and is not a new peek).
- **Metric set, for v2-wcap and the frozen v2 on the same OOS:** trades, matches, wallets; $ P&L;
  per-share net with match-clustered (engine.metrics, 1,000 draws, seed 0) and wallet-clustered
  (1,000 draws, seed 0) 95% CIs; calendar-day Sharpe with stationary-bootstrap 95% CI (mean block 5
  days, 10,000 draws, seed 20261003, as `scripts/rigor_pack.py`); max drawdown $; worst day $;
  top-1 / top-5 wallet share of P&L; per-share net without the top 5; largest wallet's share of
  gross $; worst wallet-day P&L; capital. Pre-declared decomposition rows, same metrics, no selection:
  cap only (`W1000_Roff`) and retirement only (`Winf_Ron`).
- **Per-match loss, IS and OOS, frozen v2 and v2-wcap:** worst match, p99 and p99.9 match loss,
  matches losing more than $95, worst day, share of two-sided matches, max running |net|, max match
  gross, max order, and the same book with a fixed $1,000 daily stop in the engine.

## Fail rule
v2-wcap **passes** only if, on the burned OOS, both hold:
- (a) its top-5 wallet share of P&L is lower than the frozen v2's on the same OOS, and
- (b) its per-share net is > 0 with a match-clustered 95% CI that excludes 0.

Otherwise it **fails**. The result is reported either way, with the non-blind label. No parameter is
changed after the run. If the script crashes after the log line, only the code is fixed (no
parameter), the run is repeated once, and a second log line says so. The per-wallet loss bound
($1,000 + fees a day) holds by construction whatever the verdict; the verdict is about whether the
cap also fixes concentration without killing the edge.
