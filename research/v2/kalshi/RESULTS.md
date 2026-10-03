# Lens "kalshi": Kalshi vs Polymarket lead-lag on in-play tennis, and laggard strategies

All numbers are in-sample (IS) only: matches starting before 2026-08-25 14:15 UTC. No OOS data was used.
Every parameter choice is walk-forward: picked on months < m, applied to month m.

## TL;DR

1. **Kalshi leads Polymarket.** I matched 5,037 IS ATP/WTA matches to Kalshi's `KXATPMATCH`/`KXWTAMATCH` markets. On the
   4,998 matches where both tapes exist, Kalshi traded **6.1x Polymarket's in-play notional** ($3.34B vs $0.55B;
   28.2M vs 4.8M prints). Across **106,347 point-level repricings where both venues moved at least 2c**, Kalshi
   reached the half-way point first in **68.9%** of events. Polymarket was first in 24.9%, and 6.2% were tied
   to the second. The median lead was **5 s** overall: **6 s while Polymarket's taker delay was 3 s, 4 s after it
   dropped to 1 s**, and 4 s in the current 1 s/5% regime, where Kalshi was first 73.2% of the time.
   The 1 s-return cross-correlation peaks at Kalshi-leads-by-4 s (ρ = 0.158) in the 1 s regime and by 6 s in the
   3 s regime. The whole lead distribution moves by about the change in Polymarket's speed bump
   (fig_lead_hist.png). So most of the lag is mechanical: Polymarket holds taker orders for the delay, and its
   tape is stamped with ~2 s Polygon block times. It is not an information gap.
2. **Trading the laggard remotely is not a deployable profit in the current regime.** The best strategy here takes
   Polymarket when it is stale against Kalshi and hedges at once on Kalshi, which locks the P&L. Walk-forward over
   all IS months with the 5% fee applied everywhere, it nets +1.06c/share [0.71, 1.54] (pre-declared variant) or
   +1.22c/share [0.76, 1.84] (sweep-resistant Kalshi fair, a post-hoc variant). In the **current 1 s/5% regime**
   the same rules net only **+0.06c [-1.17, 1.48] on 119 trades** and **+0.79c [-0.62, 2.79] on 86 trades**,
   about $1k in 6 weeks. Deployable notional is about **$9k/month**, because stale Polymarket liquidity is thin.
3. **Everything hinges on one unmeasured number:** how far Polymarket's data-api timestamp (block time) lags the
   real CLOB match time ("B"). The hedged edge falls about 0.4c per second of extra execution lag over all IS, and about 1c per second in the current regime. With B = 0
   s the pre-declared variant earns +1.86c [1.60, 2.16] over all IS (strict hedge in the current regime: +2.3c on 286 trades). The
   base case B = 2 s gives +1.06c. Measuring B live takes minutes and belongs to the latency lens (see
   Next steps).
4. **The reverse trade loses money.** Taking Kalshi when Polymarket jumps first is negative under every exit
   and delay assumption. Polymarket rarely leads, and Kalshi's taker fee is 0.07·p(1-p), i.e. 1.75c at p = 0.5.
5. **The passive version (quote Polymarket using Kalshi as the fair-value oracle) is not proven.** It looks
   strong (+0.63c/share, 48.6k fills in 1 s/5%) only under an optimistic fill model where you are filled at
   the print price. Under the consistent model, where you rest at Kalshi fair ± h and get filled at your own price,
   the walk-forward never finds a positive training edge, so it never trades. That model turns positive only if
   the cancel deadline is 0–1 s instead of 2 s (B sensitivity).
6. **The fast tier trades at the same moment Kalshi reprices, not after it.** At the block timestamp of a
   fast-tier print, Kalshi's mid 1 s earlier was already at their price (+0.07c beyond it). At t-5 s, Kalshi was
   still 1.52c behind. Everyone else trades 0.63c worse than Kalshi's t-1 fair. 32% of fast-tier prints had
   Kalshi already 1c or more ahead, against 18% for others. Both venues then move +1.47c their way within
   30 s. They are as fast as Kalshi's fastest participants and are not lagged Kalshi-followers, which fits
   "copying them 3 s later loses".

## 1. Data and matching (k01–k03)

- **Endpoints** (public, no auth, read-only): `GET /series`, `/markets` (live tier, `min/max_settled_ts`),
  `/historical/markets`, `/historical/trades`, `/markets/trades`, `/historical/cutoff`, `/series/fee_changes`.
  Base: `https://api.elections.kalshi.com/trade-api/v2`.
  - Kalshi splits data into a live tier and a historical tier. The cutoff on 2026-10-03 was 2026-08-04 for
    both markets and trades, so most of IS comes from `/historical/*`.
  - Trades carry microsecond `created_time`, `yes_price_dollars`, `count_fp`, `taker_side` and
    `is_block_trade`. Block trades are excluded.
- **Series used:** `KXATPMATCH` (8,772 markets / 4,386 events) and `KXWTAMATCH` (8,482 / 4,241). Only markets
  settled before the OOS cutoff were kept. Each match is two binary markets, one per player, with separate
  books. I use both, mapped onto Polymarket's outcome-0 probability axis:
  - player-0 market: p0 = yes price; taker 'yes' lifts the o0 ask.
  - player-1 market: p0 = 1 - yes price; taker 'no' lifts the o0 ask.
- **Matching:** series plus both players' surnames (accent/hyphen-insensitive, both orientations scored,
  ambiguous orientations dropped), with the Kalshi ticker date within ±2 days of Polymarket's start. Kalshi's
  close time must fall in [PM start - 1 h, PM end + 3 h], and settlements must agree.
  - **5,037 matches** (48% of 10,467 IS Polymarket matches).
  - By month: Oct 364, Nov 95, Dec 14, Jan 707, Feb 685, Mar 235, Apr 609, May 786, Jun 466, Jul 518, Aug 558.
  - By regime: 0%/3s 2,029; 3%/3s 935; 3%/1s 997; **5%/1s 1,076**.
  - Two matches where Polymarket paid 1/0 but Kalshi settled at a "fair price" after a retirement are kept,
    so the hedge P&L carries that settlement basis risk. That is 2 of 5,078, about 0.04%.
- **Kalshi trades:** 28.76M prints over 10,074 player markets, in each match's window [PM start - 15 min,
  min(PM end, Kalshi close) + 5 min]. That is 1.3 GB cached in `data/v2_kalshi/trades/`. The latest timestamp
  is 2026-08-25 06:01 UTC, before the cutoff.
  - Fetched with 4 threads at ≤ 8 req/s total, about 40% of the Basic read budget of 20 req/s, with
    exponential back-off on 429.

### Venue facts (Kalshi)
- **Fees.** Both match series switched to `quadratic_with_maker_fees` on 2025-11-15 (`/series/fee_changes`).
  - Taker fee = round-up(0.07 · C · P · (1-P)); maker fee = round-up(0.0175 · C · P · (1-P)).
  - Per contract at p = 0.5 that is 1.75c taker and 0.44c maker.
  - Docs: the trade fee is rounded up to $0.000001 and balances to the cent, with a per-order rounding
    accumulator. For orders of 100+ contracts the rounding is under 0.01c/contract and is ignored.
  - Source note: the formula comes from secondary fee guides that agree with each other. kalshi.com's fee PDF
    returned HTTP 429 (bot protection) and I did not try to bypass it.
- **Tick:** 1c (`linear_cent`). Polymarket's is 0.1c.
- **Order delay:** the market, series and docs APIs expose no delay parameter. Press reports (Dec 2025) say
  Kalshi filed with the CFTC for order-execution delays against courtsiding, with undisclosed scope. I tested
  Kalshi delays D_K = 0, 1 (base) and 3 s. The PM→Kalshi trade is negative under all three.
- **Liquidity:** in-play Kalshi notional is 6.1x Polymarket's on the same matches. The median ratio of
  Kalshi to Polymarket volume per match is 4.7x.

## 2. Lead-lag (k04)

Kalshi timestamps are microsecond trade times floored to the second. Polymarket timestamps are data-api
whole-second Polygon block times; the gap between distinct timestamps has a mode of 2 s, which confirms block
stamping. Both venues use the same mid proxy: the mean of the latest bid-side and ask-side prints that are at
most 30 s old.

| measure | all | PM delay 3 s | PM delay 1 s | 5%/1s (current) |
|---|---|---|---|---|
| events where both venues moved ≥ 2c | 106,347 | 59,951 | 46,396 | 24,188 |
| Kalshi reaches half-way first | 68.9% | 68.1% | 69.9% | 73.2% |
| same second | 6.2% | 5.2% | 7.6% | 7.5% |
| Polymarket first | 24.9% | 26.7% | 22.6% | 19.4% |
| median lead (s, >0 = Kalshi first) | 5 | 6 | 4 | 4 |
| IQR of lead (s) | [0, 14] | [-1, 16] | [0, 12] | [0, 14] |
| 1 s return cross-correlation, peak lag | -4 s | -6 s (ρ 0.010) | -4 s (ρ 0.158) | |

- **Event definition.** Events are anchored on jumps detected by either venue: Polymarket's `jumps_is`
  plus the same detector run on Kalshi prints, merged within 30 s when they point the same way.
  - pre = median mid over [A-60, A-30]; post = median mid over [A+30, A+60].
  - t50 = first second at which the mid has covered half of (post - pre).
- **Over time.** Kalshi's first-mover share rose from 0.65 (Oct 2025) to 0.75 (Aug 2026). The median lead
  went from 7 s to 4–5 s.
- **Average path** (fig_event_path.png). At the anchor, Kalshi has completed 79% of the eventual move and
  Polymarket 61%. Polymarket only catches up about 30 s later.
- **Caveat.** Polymarket's apparent lag includes the block-timestamp offset B, roughly 1–2 s. After removing
  B and the 1 s delay, the "reaction" part of the lag in the current regime is about 1–2 s.

Files: `out/leadlag_summary.json`, `out/leadlag_events.parquet`, `out/ccf*.csv`, `out/event_avg_path.csv`,
`out/fig_lead_hist.png`, `out/fig_event_path.png`, `out/fig_ccf.png`.

### Fast tier vs Kalshi (k04 part C)

Sample: all prints in the 0-3 s bucket; fast tier = the walk-forward-selected wallets from `shadow_is_uncapped`.
Each value is direction × (Kalshi mid at t-k minus the print price), where t is the Polymarket block timestamp.

| | n | Kalshi t-10 | t-5 | t-1 | Kalshi ≥1c ahead at t-1 | PM 30 s markout | Kalshi 30 s markout |
|---|---|---|---|---|---|---|---|
| fast tier | 60,366 | -2.20c | -1.52c | +0.07c | 32% | +1.48c | +1.47c |
| everyone else | 167,674 | -1.26c | -0.97c | -0.63c | 18% | -0.31c | -0.34c |

## 3. Laggard taker strategies (k05–k06)

### Signals (all real time; parameters not tuned)
- **S_PM (Kalshi leads → take Polymarket):**
  - `jump`: the src jump detector (J = 4c) run on Kalshi prints, firing at the triggering Kalshi print.
  - `gap`: the "stale laggard" trigger. Kalshi's mid moved ≥ 2c in the last 10 s and sits ≥ 2c away from the
    Polymarket mid in the same direction (20 s refractory).
  - `gaprob` (post-hoc, disclosed): the same trigger with a sweep-resistant Kalshi fair (5 s rolling medians
    of each side's prints).
- **S_K (Polymarket leads → take Kalshi):** the Polymarket `jumps_is` detect_ts, a block time and therefore
  already conservative.

### Execution
- **Polymarket fill:** the first Polymarket print on the signal side with block ts ≥ ceil(t_s + L + D + B),
  where L = 0.25 s network, D = the match's taker delay (1 or 3 s) and B = block-time allowance (2 s base;
  0 and 4 tested). No print within 3 s means no fill.
  - Kalshi fill for S_K: the first Kalshi print on that side at ts ≥ t_s + 0.25 + D_K, with D_K = 1 s base
    (0 and 3 tested).
- **Limit order:** a fill only counts if the fill price beats the leader's fair at signal by ≥ E.
- **Sizing:** min($1,000, 50% of the same-side print volume in the 3 s after the fill within the limit),
  capped at $3,000 per match.

### Exits
- **res:** hold to resolution.
- **mid60:** exit passively at the +60 s mid. Optimistic, since it assumes the resting exit fills at mid.
- **taker60:** cross the spread at +60 s and pay the fee again.
- **hedge:** at the earliest moment the Polymarket fill can be known (t_s + L + D + 0.5 s), take the opposite
  side on the other venue and hold both legs to resolution.
  - The P&L is locked except for settlement basis. Per-trade standard deviation is 6.8c against 45.8c for
    hold-to-resolution, about 7x less noise.
  - If nobody printed on the hedge side within 3 s, the hedge price is proxied conservatively as the
    other side's last print (≤ 5 s old) ∓ 2c.
  - `hedge_strict` drops those trades instead, which is a selection-biased lower check.
  - All fees are charged on every leg: Polymarket taker fee_rate·p(1-p); `curfee` = 5% applied to every month.

### Walk-forward
- Grid: G (min leader-vs-laggard gap at signal) ∈ {0,1,2,3,4,6}c × E (min edge of fill vs leader fair)
  ∈ {none,0,1,2,3}c = 30 cells.
- The cell is chosen to maximise training mean c/share (≥ 150 training trades) on months < m and applied to m.
- The first evaluation month is Dec 2025.
- If no cell has a positive training mean, the strategy stands aside for that month.

### Results (net c/share, cluster-bootstrap 95% CI by match; $ P&L on $50k notional base; Sharpe from daily P&L)

| variant (walk-forward) | n | net c/share [95% CI] | $ P&L | Sharpe | months $>0 / traded | 1s/5%: n | 1s/5%: c/share [CI] | 1s/5%: $ |
|---|---|---|---|---|---|---|---|---|
| pm_gap_curfee:ps_hedge (**pre-declared primary**) | 2069 | 1.06 [0.71, 1.54] | 7566 | 5.5 | 9/9 | 119 | 0.06 [-1.17, 1.48] | 829 |
| pm_gap_curfee:ps_hedge_strict | 1214 | 0.81 [0.24, 1.56] | 7082 | 5.2 | 9/9 | 99 | 0.19 [-1.31, 1.78] | 830 |
| pm_gaprob_curfee:ps_hedge (**best taker, post-hoc family**) | 1700 | 1.22 [0.76, 1.84] | 7013 | 4.6 | 8/9 | 86 | 0.79 [-0.62, 2.79] | 1035 |
| pm_gaprob_curfee:ps_hedge_strict | 934 | 1.15 [0.42, 2.22] | 6680 | 4.5 | 8/9 | 74 | 0.99 [-0.71, 3.15] | 1032 |
| pm_jump_curfee:ps_hedge | 796 | 1.02 [0.63, 1.43] | 2868 | 2.9 | 9/9 | 40 | -0.80 [-2.20, 0.69] | 298 |
| pm_jump_curfee:ps_hedge_strict | 473 | -0.40 [-0.88, 0.09] | 2469 | 2.5 | 8/9 | 26 | -1.53 [-3.22, 0.30] | 286 |
| pm_gap_curfee:ps_mid60 | 3075 | -0.17 [-0.48, 0.14] | 4795 | 2.5 | 5/7 | 155 | 0.95 [-0.78, 2.70] | 783 |
| pm_gaprob_curfee:ps_mid60 | 850 | -0.61 [-1.17, 0.00] | 2333 | 5.1 | 1/1 | 0 | | |
| pm_jump_curfee:ps_mid60 | 716 | -0.12 [-0.66, 0.43] | 2079 | 2.2 | 4/6 | 69 | 1.13 [-1.35, 3.52] | 1467 |
| pm_gap_curfee:ps_res | 2855 | -0.52 [-2.77, 1.68] | -2141 | -0.4 | 2/3 | 0 | | |
| pm_gaprob_curfee:ps_res | 1395 | -0.37 [-3.15, 2.29] | -6170 | -2.2 | 0/2 | 0 | | |
| pm_jump_curfee:ps_res | 1923 | -1.88 [-4.40, 0.53] | -8434 | -1.5 | 1/3 | 0 | | |
| pm_*_curfee:ps_taker60 (all three) | 0 | stands aside (no positive training edge) | | | | | | |
| k_jump:ps_hedge (PM leads → take Kalshi) | 408 | -0.81 [-1.93, 0.97] | -1340 | -1.0 | 2/9 | 64 | -2.77 [-3.63, -1.82] | -907 |
| k_jump:ps_hedge_strict | 321 | -1.19 [-2.06, -0.18] | 250 | 0.3 | 4/9 | 34 | -3.80 [-4.50, -3.08] | -724 |
| k_jump:ps_res | 529 | -2.67 [-7.11, 2.14] | -14762 | -2.0 | 2/9 | 91 | -3.17 [-12.08, 5.60] | -4097 |
| k_jump:ps_mid60 / ps_taker60 | 0 | stands aside | | | | | | |

The same variants with each match's own historical fee rather than 5% are in `out/backtest_summary.json`. For
example, `pm_gap:ps_hedge` earns +1.87c [1.52, 2.36] over all IS; its 1s/5% rows are identical.

**Baseline without a walk-forward filter** (every gap signal, G = 0 and no E, 5% fee, 1 s/5% months):
hedge -2.98c, mid60 -0.57c, resolution -0.52c per share. Chasing Kalshi moves blindly loses money; only the
far-stale subset (G = 6c, E = 3c, chosen in every month) pays.

#### Walk-forward by month: pre-declared primary `pm_gap_curfee:ps_hedge`

| month | G | E | train c | train n | n | c/share | $ P&L | $ deployed |
|---|---|---|---|---|---|---|---|---|
| 2025-12 | 6c | 3c | 2.43 | 578 | 17 | 2.97 | 306 | 2,976 |
| 2026-01 | 6c | 3c | 2.44 | 597 | 774 | 1.80 | 2,098 | 35,452 |
| 2026-02 | 6c | 3c | 2.03 | 1,398 | 565 | 0.74 | 1,615 | 36,783 |
| 2026-03 | 6c | 3c | 1.64 | 1,980 | 88 | -0.21 | 1,311 | 6,710 |
| 2026-04 | 6c | 3c | 1.56 | 2,068 | 268 | -0.35 | 310 | 34,441 |
| 2026-05 | 6c | 3c | 1.33 | 2,345 | 173 | 2.90 | 658 | 14,691 |
| 2026-06 | 6c | 3c | 1.43 | 2,524 | 65 | -0.99 | 440 | 5,054 |
| 2026-07 | 6c | 3c | 1.37 | 2,589 | 59 | -0.03 | 319 | 6,250 |
| 2026-08 | 6c | 3c | 1.33 | 2,650 | 60 | 0.14 | 509 | 8,453 |

#### Walk-forward by month: best taker `pm_gaprob_curfee:ps_hedge`

| month | G | E | n | c/share | $ P&L | $ deployed |
|---|---|---|---|---|---|---|
| 2025-12 | 6c | 3c | 22 | 3.22 | 325 | 3,249 |
| 2026-01 | 6c | 3c | 693 | 1.86 | 1,892 | 32,904 |
| 2026-02 | 6c | 3c | 462 | 0.55 | 1,161 | 27,879 |
| 2026-03 | 6c | 3c | 66 | -0.95 | 29 | 4,139 |
| 2026-04 | 6c | 3c | 197 | -0.31 | 572 | 27,088 |
| 2026-05 | 6c | 3c | 133 | 4.01 | 1,606 | 11,394 |
| 2026-06 | 6c | 3c | 41 | -0.52 | 393 | 4,706 |
| 2026-07 | 6c | 3c | 44 | 0.34 | -29 | 7,826 |
| 2026-08 | 6c | 3c | 42 | 1.26 | 1,064 | 10,373 |

$ P&L can be positive in months with a negative equal-weighted c/share, because the size rule puts more
money behind trades with more stale volume.

**By regime** for the primary: 0%/3s +1.31c [1.00, 1.61] (n 1,412); 3%/3s +0.89c [-0.63, 3.28] (351);
3%/1s +0.11c [-0.60, 0.83] (187); 5%/1s +0.06c [-1.17, 1.48] (119). Even with the 5% fee applied to every
month, the edge is concentrated in the 3 s-delay era. After the move to a 1 s delay it all but disappears:
Polymarket reprices faster and competition from other Kalshi-watchers increased.

### Latency sensitivity (robustness only, never selected on)

| variant | B (PM block allowance) | all-IS c/share [CI] | n |
|---|---|---|---|
| pm_gap_curfee:ps_hedge | 0 s | 1.86 [1.60, 2.16] | 2,989 |
| pm_gap_curfee:ps_hedge | 2 s (base) | 1.06 [0.71, 1.54] | 2,069 |
| pm_gap_curfee:ps_hedge | 4 s | 1.02 [0.57, 1.58] | 1,412 |
| pm_gaprob_curfee:ps_hedge | 0 / 2 / 4 s | 2.05 / 1.22 / 1.24 | 2,571 / 1,700 / 1,143 |
| pm_gap_curfee:ps_mid60 | 0 / 4 s | 1.39 [1.15, 1.64] / stands aside (training edge <= 0) | 5,277 / 0 |

In the current regime, the strict-hedge `gap` variant gives +2.29c on 286 trades at B = 0, +0.19c at B = 2 and
-0.48c at B = 4. For `gaprob` strict it is +3.06 / +0.99 / -0.28c. PM→Kalshi with D_K = 0 or 3 s is negative
throughout. The full table is `latency_sensitivity` in `out/backtest_summary.json`.

## 4. Passive variant: quote Polymarket with Kalshi as the oracle (k08; family added post hoc, disclosed)

Polymarket makers can cancel instantly while takers wait D. A maker that pulls quotes when Kalshi moves
against them only trades with takers whose price is still on the right side of Kalshi's fair value at the
cancel deadline.

Method:
- For every Polymarket taker print, compute edge = dir · (p - Kalshi mid at t - B - 0.3 s) with B = 2.
- Fill when edge ≥ h, with h ∈ {none, 0, 0.5, 1, 2, 3}c chosen walk-forward.
- Participation is 25% of the print, ≤ $250. The maker rebate is 0.15 · rate · p(1-p).

Two fill-price models:
- **print-price (optimistic):** the maker is filled at the print price p.
  `maker_curfee:ps_pm60` (+60 s Polymarket-mid markout): all IS **+1.03c [0.96, 1.13]**, 255k fills,
  9/9 months; **1s/5% +0.63c [0.41, 0.82]**, 48.6k fills, $31.8k. Hold to resolution: -0.18c [-2.20, 1.57].
  Hedged at once on Kalshi as a taker: -0.20c [-0.32, -0.08].
- **quote-price (consistent):** the maker rests at Kalshi fair ± h, so a qualifying taker fills it at
  fair ± h, not at p. Training mean c/share was negative in every month (-1.5 to -0.5c), so the walk-forward
  **never trades**.
  - Plain in-sample average, not walk-forward, over 1s/5% prints: from h = 0c to 3c it is between -0.74c and
    -0.90c on the +60 s PM mid, and -0.44c on the Kalshi mid at h = 3c.

The print-price model's profit therefore comes from prints executed well beyond Kalshi fair, i.e. sweeps and
stale wide quotes. A maker quoting at fair ± h does not capture those prices.

Cancel-deadline sensitivity: in 1s/5% the quote-price model gives +0.37c [0.14, 0.61] with B = 1 (n 36.6k)
and +1.15c [0.90, 1.41] with B = 0. Under the stand-aside walk-forward, B = 1 still does not trade, because the
early months' training edge is negative.

Conclusion: the passive trade is the economically natural way to monetise the lead, but trade prints cannot
establish it. It needs order-book data plus a measured B.

## 5. Capacity

Hedged taker, current regime: $6–10k notional per month, roughly 45–60 trades/month with a median of $17 per
trade, and about $0.5–1k P&L per month. The binding constraint is the volume left at stale Polymarket prices
3–6 s after a Kalshi move. The Kalshi hedge leg is not the constraint, since Kalshi is 6x deeper. Capital
needed is about $1 per hedged share pair, tied up until resolution (1–3 h), so roughly $5k of capital covers it.

## 6. Variant count

1,904 walk-forward variant evaluations in total:
- k06: 1,770 = 4 signal families × fee settings × 5 exits × 30 (G, E) cells, plus latency sensitivity
  (3 families × 2 B × 3 exits × 30, and PM→Kalshi 2 D_K × 3 × 30).
- k08: 134.

Earlier development runs on the Oct–Dec 2025 subset used the same code paths.

Post-hoc changes, all disclosed:
- Moved the hedge time to the earliest feasible moment. This is the conservative direction: hedging later
  flattered P&L because Kalshi keeps drifting the same way.
- Added the hedge touch-proxy, first ±1c, then switched to the more conservative ±2c / ≤ 5 s.
- Added the `gaprob` family.
- Added the maker family and its quote-price model.
- Added the stand-aside rule.

## Caveats

- **The PM timestamp offset B is not measured.** Results move by about 1c/share between B = 0 and B = 2.
  B = 2 s is the base: Polygon blocks are about 2 s apart, plus relayer latency. Taker fills use prints with
  block ts ≥ ceil(t_s + L + D + B), which is conservative if B_true < 2.
- **The fills are only proxies.** No historical order books exist for either venue, so fills are inferred
  from the first same-side print after execution time. Queue priority is not modelled. Other Kalshi-watchers
  compete for the same stale quotes, and size is capped at 50% of observed volume.
- **The hedge proxy matters.** Hedges without a print on the hedge side within 3 s (about 40% of selected
  trades) use the other side ∓ 2c. `hedge_strict` drops them instead; both are reported.
- **The current regime sample is small.** Only about 6 weeks of IS data are 1 s/5% (Jul–Aug 2026). That is
  74–119 hedged trades, too few to separate +1c from 0.
- **The fee formula is secondary-sourced.** It comes from fee guides and the API's `fee_type`, not the
  official PDF, which was blocked. Kalshi's in-play order delay, if any, is unknown, so D_K was tested at
  0, 1 and 3 s.
- **Legal access is a real constraint.** Kalshi is US-KYC only and Polymarket's international book is
  geofenced from US persons. Running both legs as one entity may not be legally possible. Polymarket US is a
  separate book and was not studied.
- **OOS hygiene.**
  - While discovering the API, one `GET /markets?series_ticker=KXATPMATCH&status=settled&limit=3` call and
    one events listing (titles only) returned metadata for Oct 2026 matches. Nothing from those was stored
    or used.
  - All stored Kalshi data closes before the cutoff.
  - No Polymarket OOS data or `data/locked/` was read, and no live recordings were analysed.
- **The fast-tier analysis has the same B uncertainty.** "Kalshi at t-1" is relative to the Polymarket block
  timestamp.

## Next steps (highest value first)

1. **Measure B.** For the same Polymarket trades, compare the CLOB websocket `last_trade_price` receive time
   with the data-api `timestamp`. This belongs to the latency lens and its live recorder. If B ≤ 1 s, the
   hedged taker is roughly +1.5–2c in the current regime and the passive maker turns positive. If B ≈ 2 s,
   neither is worth deploying.
2. **Record both books live (forward only).** Kalshi orderbook polling plus the Polymarket CLOB ws, to replace
   print-based fill proxies with real touch and depth. This is the only way to validate the maker variant.

## Reproduce (from repo root)

```
.venv/bin/python research/v2/kalshi/run.py              # all steps (network steps k01-k03 are cached)
.venv/bin/python research/v2/kalshi/run.py --offline    # analysis only, from data/v2_kalshi cache (~8 min)
# or step by step:
.venv/bin/python research/v2/kalshi/k01_enumerate.py   # Kalshi IS markets (historical + live tier < cutoff)
.venv/bin/python research/v2/kalshi/k02_match.py       # match to Polymarket IS universe -> data/v2_kalshi/matched.parquet
.venv/bin/python research/v2/kalshi/k03_fetch.py       # Kalshi trade tapes (~70 min uncached at 8 req/s)
.venv/bin/python research/v2/kalshi/k04_leadlag.py     # lead-lag + fast-tier check
.venv/bin/python research/v2/kalshi/k05_signals.py     # signal/fill tables
.venv/bin/python research/v2/kalshi/k06_backtest.py    # taker walk-forward + latency sensitivity
.venv/bin/python research/v2/kalshi/k08_maker.py       # passive (maker) family
.venv/bin/python research/v2/kalshi/k09_report.py      # figures + results.json
```

Outputs:
- `research/v2/kalshi/results.json`
- `research/v2/kalshi/out/`: summaries, every walk-forward table (`wf_*.csv`), walk-forward trades
  (`trades_wf_*.parquet`), IS transparency grids (`grid_IS_*.csv`), and figures `fig_lead_hist.png`,
  `fig_event_path.png`, `fig_ccf.png`, `fig_wf_primary.png`, `fig_wf_best_taker.png` and `fig_wf_maker.png`.
