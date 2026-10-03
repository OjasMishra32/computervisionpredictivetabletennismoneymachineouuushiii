# Lens "sizing": sizing and decision-time filters for the fast-tier edge (IS only)

**Bottom line.** Size each trade by its resolution risk, not its dollars. Only follow wallets whose
past edge covers today's fee. Cap each match's *net* outcome exposure at 100 shares. Walk-forward on
IS Feb to Aug 2026, held to resolution, this changes the shadow book as follows:

- Sharpe goes from 5.97 to **16.8**.
- Max drawdown goes from −37% to **−4.0%** of capital. The worst day goes from −14.9% to −2.1%.
- The worst single match goes from −$3,098 to −$155.
- **7/7 months are positive** (6/7 before).

In the current 1 s / 5% regime the policy nets **+0.89¢/share [0.47, 1.31]** held to resolution and
**+0.78¢ [0.68, 0.88]** at the 30 s mark. The baseline nets +0.59¢ [0.44, 0.74] at the 30 s mark.
The cost is dollars: $43k instead of $321k over 7 months. Capital falls too, from $102k to $23k.
Most of the baseline's extra P&L is resolution noise: in the 1 s/5% period, $90k of its $121k came
after the 30 s mark. That same exposure is what lost $36k out of sample.

Everything below uses IS data only. Months, regimes and P&L are measured on matches that start
before 2026-08-25 14:15 UTC. No OOS row, no `data/locked/` and no post-cutoff market data was read.

## 1. Setup

- **Opportunity set.** `data/derived/shadow_is_uncapped.parquet` holds every 0–3 s print by a wallet
  qualified walk-forward (src.fasttier rules) as fast tier: 138,691 prints in 8,514 matches.
- **Evaluation months.** 2026-02 to 2026-08: 7 months, 206 days. Dec 2025 and Jan 2026 are training
  only. Jan is simulated as a warm-up that gives the daily-stop and meta-selection rules a history.
- **Walk-forward fitting.** For each month m, everything a policy estimates is fitted on rows with
  month < m and then applied to m. That covers:
  - edge by price bucket and variance;
  - wallet quality;
  - the deployment scale that sets the risk budget R;
  - the price zone;
  - the fill-move threshold;
  - the daily-stop sigma.
- **Sequential limits.** Per-match, net-exposure, per-day and per-wallet-day caps and daily stops are
  applied in time order. They use only trades already taken.
- **Liquidity constraint.** We never take more shares than the fast-tier print itself, or more than
  $1k per trade. This is the shadow-book assumption that we replace their fill.
- **P&L measures**, per share:
  - `res`: `dir·(res−p) − fee`, held to resolution, with 50/50 resolutions included.
  - `m30`: `mo30 − fee`, exiting at the mid 30 s later. This is optimistic because it assumes a free
    maker exit.
  - `m30x`: the 30 s exit as a taker, paying a second fee plus a 0.5¢ half spread. This is
    pessimistic.
- **Fee modes.** `actual` uses each match's own fee. `5pct` re-prices every match at today's
  0.05·q(1−q), which lets us judge rules over all 7 months as if today's fee had applied.
- **Capital** = 3 × peak gross dollars locked in open positions, with lock-up to match end capped at
  8 h. Sharpe is annualised from daily P&L, zero days included.
- **CIs** are 95% cluster bootstraps over matches, 1000–2000 draws.
- **Per-share figures** are share-weighted (Σpnl/Σshares) unless labelled per print.

## 2. What the data say at decision time (descriptive, all IS months; `out/edge_by_*.csv`)

These tables span all IS months. No rule was taken from them directly.

| Feature | Finding (net30 at 5% fee, ¢/share) | Usable? |
|---|---|---|
| Token price q | Gross 30 s markout is flat at 1.5–1.7¢ for q in 0.1–0.85 and falls above 0.9. The fee 5q(1−q) makes the net edge U-shaped: 0.41–0.43 at q 0.4–0.6, 0.77–1.02 at q 0.1–0.2 and 0.8–0.9 (`fig_edge_by_q.png`). Resolution variance per share is q(1−q). | Yes, clean |
| Ticket size (their $) | Flat from $5 to $2.5k+ (0.65–1.04). Only ≤$5 clips are weaker (0.40). **Big tickets do not have lower edge in IS.** The OOS dollar loss is resolution variance, not adverse selection. | Yes, clean |
| Wallet | Strong heterogeneity. One high-volume qualified wallet has net30 of −0.42¢ over 34k prints. | Yes, if estimated on months < m |
| fill_move = (p − VWAP[t−63,t−3))·dir | Very steep inside the window: +2.85 at (0, 2¢], −0.99 at ≤ −2¢. | **No, window-contaminated** |
| pre_move, n_prior3, clip_k, spread0 | First clips with no prints in the prior 3 s earn more (0.74 against 0.07–0.27). | **No, window-contaminated** |

**Window-contamination test** (`mech_check.py`, `allbucket_check.py`). The 0–3 s bucket is defined
by a jump detector that looks up to 10 s past the onset. So a fill only a little above the pre-event
level, inside a confirmed ≥4¢ jump, is partly guaranteed a further move. Two checks:

- **Slow takers in the same window** show the same fill_move gradient: +2.1¢ at (2, 3]¢ and −0.1¢ at
  (4, 5]¢.
- **The same fast wallets outside the 0–3 s window** show no falling gradient: gross is 0.7–1.4¢
  across fill_move buckets, if anything rising with fill_move.

The n_prior3 effect shrinks from 0.65¢ to about 0.15¢ outside the window. These features are
therefore reported (B6–B8, marked *) but excluded from the recommended policy and from the clean
meta-selection menu.

## 3. Variants (all walk-forward; full table in `out/policies.csv`, definitions in `out/policy_definitions.csv`)

Columns:
- **res** = held to resolution, actual fee.
- **m30** = exit at the 30 s mid, actual fee.
- **1s/5%** = the Jul 11 – Aug 25 matches.
- **A1–A7** are deployed at 50% of the baseline's training-period mean dollars. No rule may exceed
  the baseline's min(print, $1k) on any trade, so sizing shapes are only comparable at equal
  deployment.
- **Risk budget R.** The deployment fraction fixes R walk-forward: about $25 at 25%, $100 at 50% and
  $280 at 75%. At 100% the risk-parity cap no longer binds, so "100%" rows are the $ mirror plus
  wallet filter, zone and net cap.

| Policy | res ¢/sh | res $k | res Sharpe | max DD % | worst day % | months + | capital $k | m30 ¢/sh | m30 Sharpe | 1s/5% res ¢/sh | 1s/5% m30 ¢/sh |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **A0 baseline**: $ mirror, ≤$1k/trade, ≤$3k/match | 2.13 | 320.8 | 5.97 | −37.1 | −14.9 | 6/7 | 102.0 | 1.03 | 16.4 | 2.25 | 0.59 |
| A1 take ½ of each print ($ mirror) | 1.97 | 166.1 | 5.28 | −48.4 | −18.0 | 6/7 | 53.3 | 1.03 | 17.0 | 1.81 | 0.63 |
| A2 share mirror (constant share cap) | 1.59 | 116.6 | 7.43 | −20.9 | −10.3 | 7/7 | 61.7 | 1.08 | 24.6 | 1.15 | 0.76 |
| A3 risk parity: shares ≤ R/√(q(1−q)) | 1.62 | 117.8 | 7.78 | −19.6 | −9.7 | 7/7 | 60.1 | 1.08 | 23.5 | 1.14 | 0.75 |
| A4 Kelly: edge(q) from mo30, var q(1−q) | 1.65 | 123.5 | 8.03 | −19.3 | −10.3 | 7/7 | 57.6 | 1.05 | 21.9 | 1.16 | 0.71 |
| A5 Kelly, edge from mo_res | 1.46 | 117.2 | 5.90 | −32.8 | −16.8 | 7/7 | 57.2 | 0.99 | 22.6 | 1.08 | 0.66 |
| A6 Kelly, var = bucket var(mo30) | 1.63 | 120.0 | 7.79 | −20.8 | −10.2 | 7/7 | 60.4 | 1.07 | 24.7 | 1.18 | 0.76 |
| A7 Kelly + wallet effect | 1.68 | 119.1 | 8.02 | −18.9 | −9.1 | 7/7 | 58.4 | 1.16 | 22.0 | 1.12 | 0.84 |
| B1 price zone chosen WF (16-pt grid) | 1.86 | 246.9 | 5.15 | −38.3 | −12.9 | 6/7 | 98.9 | 1.07 | 16.2 | 1.94 | 0.59 |
| B2 zone 0.05–0.95 | 2.20 | 320.7 | 6.01 | −38.6 | −15.4 | 6/7 | 99.1 | 1.02 | 17.9 | 2.32 | 0.60 |
| B3 zone 0.10–0.90 | 2.08 | 282.3 | 5.71 | −36.1 | −15.4 | 6/7 | 97.1 | 1.01 | 19.4 | 2.50 | 0.60 |
| B4 wallet filter (past net at today's fee > 0) | 2.26 | 308.8 | 5.84 | −36.3 | −16.1 | 6/7 | 90.0 | 1.18 | 16.6 | 2.42 | 0.81 |
| B5 skip tickets < $5 | 2.15 | 316.1 | 5.93 | −38.1 | −15.4 | 6/7 | 98.1 | 1.03 | 16.8 | 2.29 | 0.59 |
| B6* first clip, no prints in prior 3 s | 2.04 | 207.6 | 5.02 | −21.7 | −15.0 | 6/7 | 80.1 | 1.20 | 20.4 | 2.13 | 0.89 |
| B7* skip fill_move ≤ −2¢ | 2.25 | 293.2 | 5.90 | −42.8 | −14.9 | 6/7 | 92.3 | 1.34 | 20.3 | 2.27 | 0.92 |
| B8* fill_move ∈ (0, X], X chosen WF | 3.82 | 246.9 | 6.35 | −37.0 | −12.9 | 6/7 | 84.9 | 1.30 | 18.7 | 5.07 | 0.95 |
| C1 match cap $1k | 1.64 | 152.3 | 4.43 | −35.0 | −12.0 | 7/7 | 71.8 | 0.94 | 19.5 | 1.25 | 0.49 |
| C2 match cap $10k | 2.04 | 350.7 | 5.43 | −52.3 | −21.1 | 6/7 | 106.7 | 1.06 | 16.8 | 1.96 | 0.70 |
| C3 no match cap | 2.05 | 353.5 | 5.48 | −53.1 | −20.4 | 6/7 | 107.8 | 1.06 | 16.7 | 1.97 | 0.70 |
| C4 net ≤ 2000 sh, match $10k | 1.53 | 200.5 | 6.61 | −24.1 | −8.8 | 7/7 | 90.3 | 1.03 | 18.7 | 1.20 | 0.56 |
| C5 net ≤ 5000 sh, match $10k | 1.88 | 296.5 | 6.24 | −33.3 | −10.6 | 6/7 | 106.7 | 1.03 | 18.8 | 2.01 | 0.61 |
| C6 net ≤ 2000 sh, match $3k | 1.54 | 193.2 | 6.63 | −22.4 | −7.2 | 7/7 | 89.0 | 1.02 | 18.7 | 1.30 | 0.57 |
| C7 wallet-day $5k | 1.71 | 197.9 | 4.10 | −63.8 | −17.4 | 6/7 | 67.1 | 0.92 | 19.4 | 1.29 | 0.65 |
| C8 wallet-day $15k | 2.13 | 315.5 | 5.92 | −38.6 | −14.9 | 6/7 | 102.0 | 1.02 | 16.7 | 2.20 | 0.59 |
| C9 day cap $50k | 2.22 | 295.5 | 5.89 | −25.3 | −13.6 | 6/7 | 102.0 | 1.01 | 17.9 | 2.06 | 0.53 |
| C10 day cap $100k | 2.07 | 309.5 | 5.91 | −37.1 | −14.9 | 6/7 | 102.0 | 1.04 | 16.4 | 2.10 | 0.60 |
| D1 $100/trade, $300/match | 1.40 | 53.0 | 4.44 | −30.1 | −9.8 | 7/7 | 36.0 | 0.93 | 20.2 | 0.70 | 0.52 |
| D2 $250 / $750 | 1.62 | 120.2 | 5.15 | −29.7 | −9.7 | 7/7 | 60.8 | 1.02 | 13.9 | 1.52 | 0.54 |
| D3 $500 / $1.5k | 1.83 | 204.0 | 5.59 | −37.8 | −13.7 | 6/7 | 79.4 | 1.02 | 16.5 | 1.79 | 0.57 |
| D4 $2.5k / $7.5k | 2.02 | 344.3 | 5.39 | −50.6 | −19.9 | 6/7 | 106.7 | 1.05 | 17.0 | 1.90 | 0.67 |
| D5 $5k / $15k | 2.05 | 353.8 | 5.48 | −53.1 | −20.4 | 6/7 | 107.8 | 1.06 | 16.8 | 1.98 | 0.70 |
| E1 daily stop −2σ (σ from earlier months) | 2.13 | 312.9 | 5.81 | −36.6 | −10.5 | 6/7 | 102.0 | 1.03 | 16.4 | 2.33 | 0.59 |
| E2 daily stop −3σ | 2.13 | 320.1 | 5.93 | −36.5 | −14.5 | 6/7 | 102.0 | 1.03 | 16.4 | 2.24 | 0.59 |
| E3 A3 + stop −2σ | 1.69 | 118.7 | 8.09 | −15.0 | −5.5 | 7/7 | 60.1 | 1.08 | 23.5 | 1.28 | 0.75 |
| F1 A3 + zone WF + wallet | 1.67 | 92.8 | 7.41 | −23.6 | −11.5 | 7/7 | 43.6 | 1.31 | 22.5 | 1.05 | 1.00 |
| F2 A3 + wallet + net ≤ 2000 | 1.86 | 115.0 | 8.74 | −20.5 | −8.2 | 7/7 | 46.6 | 1.25 | 23.7 | 1.26 | 0.93 |
| F3 A7 + zone WF + net ≤ 2000 | 1.49 | 91.1 | 7.37 | −18.0 | −7.0 | 7/7 | 55.2 | 1.18 | 23.0 | 1.12 | 0.87 |
| F4 / F5 A3 at 25% / 75% | 1.48 / 1.73 | 51.8 / 188.7 | 8.72 / 7.04 | −10.5 / −24.9 | −4.9 / −12.2 | 7/7 | 38.5 / 82.2 | 1.06 / 1.08 | 24.3 / 22.0 | 1.20 / 1.45 | 0.78 / 0.67 |
| F6 / F7 $ mirror at 25% / 75% | 2.06 / 2.06 | 88.6 / 247.4 | 5.49 / 5.77 | −51.4 / −41.5 | −20.4 / −14.5 | 6/7 | 27.0 / 80.0 | 1.07 / 1.03 | 16.8 / 16.6 | 1.99 / 1.98 | 0.71 / 0.58 |
| F8 A3 + zone 0.05–0.95 + wallet + net ≤ 2000 | 1.89 | 112.1 | 8.81 | −22.4 | −8.8 | 7/7 | 43.8 | 1.28 | 23.9 | 1.31 | 0.97 |
| F9 F8 + stop −2σ | 1.95 | 113.6 | 9.26 | −15.6 | −6.3 | 7/7 | 43.8 | 1.28 | 23.9 | 1.49 | 0.97 |
| F10 / F11 / F12 F8 at 25 / 75 / 100% | 1.84 / 1.80 / 1.70 | 50.3 / 160.7 / 185.6 | 9.59 / 7.66 / 6.55 | −15.7 / −23.8 / −26.8 | −7.0 / −10.5 / −10.4 | 7/7 | 22.9 / 65.8 / 78.9 | 1.31 / 1.25 / 1.22 | 24.6 / 22.6 / 19.2 | 1.45 / 1.45 / 1.47 | 1.03 / 0.92 / 0.88 |
| G 25% net ≤ 500 / 250 / 100 | 1.80 / 1.68 / 1.60 | 48.9 / 43.0 / 33.3 | 9.85 / 11.28 / 15.36 | −14.7 / −11.8 / −6.1 | −5.2 / −3.7 / −2.4 | 7/7 | 22.8 / 22.1 / 18.5 | 1.30 / 1.29 / 1.25 | 24.4 / 24.8 / 24.3 | 1.38 / 1.15 / 1.02 | 1.00 / 0.98 / 0.91 |
| G 50% net ≤ 500 / 250 | 1.70 / 1.67 | 88.0 / 70.6 | 10.83 / 13.86 | −17.3 / −9.7 | −5.1 / −3.4 | 7/7 | 39.8 / 34.2 | 1.25 / 1.21 | 24.3 / 23.6 | 0.90 / 0.80 | 0.88 / 0.82 |
| **G 50% net ≤ 100 (recommended)** | **1.58** | **43.3** | **16.77** | **−4.0** | **−2.1** | **7/7** | **23.2** | **1.18** | **22.9** | **0.89** | **0.78** |
| G 100% net ≤ 500 / 250 / 100 | 1.66 / 1.66 / 1.59 | 110.3 / 77.9 / 43.4 | 10.63 / 13.61 / 16.72 | −15.1 / −8.3 / −4.0 | −5.1 / −2.8 / −2.1 | 7/7 | 48.0 / 37.6 / 23.2 | 1.19 / 1.20 / 1.18 | 21.0 / 21.9 / 22.8 | 0.78 / 0.81 / 0.89 | 0.80 / 0.79 / 0.78 |

### What moved the needle

1. **Sizing shape.** At equal deployment, any rule that caps shares by resolution risk raises Sharpe
   by 40–50% and halves the drawdown, compared with the dollar mirror. That covers share mirror, risk
   parity and the Kelly variants: Sharpe 7.4–8.0 against 5.3, DD −19 to −21% against −48%. Kelly's
   edge estimates add little over plain risk parity (8.03 against 7.78). The dollar mirror buys 5–10×
   more shares in cheap tokens, so its resolution variance is dominated by a few lottery tickets.
2. **Wallet filter at today's fee.** This keeps a wallet only if its shrunk past 30 s markout
   (n0 = 200 toward the all-taker mean) exceeds 0.05·q(1−q). It lifts 1 s/5% m30 from 0.59¢ to 0.81¢
   per share on its own (B4), and to 0.97–1.03¢ combined with risk parity (F8/F10). It removes 28% of
   prints and 2 of the 72 tier wallets in Aug.
3. **Per-match net-exposure cap.** Risk-reducing trades are always allowed; risk-increasing ones are
   clipped at N outcome shares. This is the biggest lever on noise. At N = 100 the share of daily P&L
   variance that comes from resolution falls:

   | Policy | All months | 1 s/5% |
   |---|---|---|
   | Baseline | 97% | 99% |
   | Recommended (N = 100) | 70% | 93% |

   The worst single match falls from −$3,098 to −$155 (`out/noise.csv`, `out/match_tails.csv`). It
   costs about 25–35% of the 30 s edge dollars, because some skipped trades were good ones: in
   1 s/5%, m30 drops from 1.03¢ to 0.78¢ per share.
4. **No robust gain from:**
   - price-zone filters (WF zone choice lost money relative to none);
   - larger per-trade or per-match caps (Sharpe falls);
   - day caps, wallet-day caps and min-ticket filters;
   - a 3σ daily stop.

   A −2σ daily stop helps only modestly on already risk-parity books (E3, F9: about +0.3–0.5 Sharpe,
   smaller worst day). It hurts the dollar mirror (E1).
5. **Exit.** A taker exit 30 s later loses money at today's fee in every policy: in 1 s/5%, the
   baseline earns −0.83¢/share and the recommended policy −0.66¢. So hold to resolution, and use the
   net cap to remove the noise. An exit only makes sense as a passive maker order, which these data
   cannot verify.

## 4. Walk-forward by month (recommended `G_50pct_net100` vs baseline; actual fee; `out/recommended_monthly.csv`, `out/monthly.csv`)

| Month | Recommended res $ | res ¢/sh [95% CI] | m30 ¢/sh [CI] | m30x ¢/sh | Baseline res $ | Baseline res ¢/sh | Baseline m30 ¢/sh |
|---|---|---|---|---|---|---|---|
| 2026-02 (3 s/0%) | 5,671 | 1.90 [1.19, 2.59] | 0.96 [0.78, 1.14] | 0.46 | 33,711 | 2.54 | 1.18 |
| 2026-03 (3 s/0–3%) | 2,091 | 1.80 [0.65, 3.01] | 1.96 [1.69, 2.24] | 1.34 | −1,992 | −0.31 | 1.42 |
| 2026-04 (3 s/3%) | 8,923 | 2.26 [1.59, 2.87] | 1.52 [1.37, 1.67] | 0.44 | 24,996 | 1.20 | 1.21 |
| 2026-05 (3 s, 1 s /3%) | 9,674 | 1.89 [1.37, 2.43] | 1.56 [1.38, 1.74] | 0.48 | 68,689 | 2.83 | 1.77 |
| 2026-06 (1 s/3%) | 8,390 | 1.75 [1.22, 2.26] | 1.14 [1.00, 1.29] | 0.06 | 59,514 | 2.41 | 1.03 |
| 2026-07 (1 s/3%, then 5% from Jul 11) | 5,368 | 1.03 [0.54, 1.53] | 0.76 [0.64, 0.87] | −0.58 | 80,976 | 2.46 | 0.52 |
| 2026-08 (1 s/5%, to Aug 25) | 3,151 | 0.78 [0.20, 1.36] | 0.91 [0.76, 1.06] | −0.53 | 54,915 | 1.94 | 0.69 |

**By regime, held to resolution.** All rows are walk-forward rules, IS only; data in
`out/recommended_regime.csv`.

| Regime | Policy | res ¢/sh [95% CI] | m30 ¢/sh [CI] | Sharpe (regime days) | Worst day | Max DD |
|---|---|---|---|---|---|---|
| 3 s / 0% | Recommended | 1.88 [1.25, 2.47] | 1.22 | 14.2 | | |
| 3 s / 3% | Recommended | 2.07 [1.54, 2.59] | 1.53 | 21.6 | | |
| 1 s / 3% | Recommended | 1.70 [1.35, 2.08] | 1.26 | 25.3 | | |
| **1 s / 5%** | **Recommended** | **0.89 [0.47, 1.31]** | **0.78 [0.68, 0.88]** | **10.0** | **−$486** | **−$922** |
| 1 s / 5% | Baseline | 2.25 [0.51, 3.93] | 0.59 [0.44, 0.74] | 7.1 | −$15,183 | −$37,839 |

For the baseline in 1 s/5%, $90k of its $121k P&L came after the 30 s mark (resolution luck).

**Under the 5%-fee re-pricing** (every month as if today's fee applied), the recommended policy
earns 1.34¢/share [1.09, 1.58] held to resolution, with Sharpe 13.2, DD −4.8% and 7/7 months
positive. The baseline earns 1.81¢ [0.83, 2.80] with Sharpe 5.1, DD −37% and 6/7 months positive.

The per-share edge is clearly falling. The fee went 0 → 3 → 5% and qualifying wallets grew
3 → 72, and the recommended policy's monthly figure fell from about 1.9¢ to 0.8¢.

## 5. Is the selection itself honest? (`out/meta.csv`, `out/deflated_sharpe.csv`)

- **Walk-forward meta-selection.** Each month, the selector picks the policy with the best Sharpe
  over all earlier days. P&L is vol-normalised by each policy's earlier daily sd, so scale cannot
  win. The clean menu has 52 policies and excludes the window-contaminated B*. The selected series
  scores:

  | Measure, fee mode | Selected series Sharpe | Baseline Sharpe (same units) |
  |---|---|---|
  | res, actual fee | 16.5 | 5.8 |
  | res, 5% re-priced | 9.9 | 4.8 |
  | m30, actual fee | 23.2 | 15.8 |
  | m30, 5% re-priced | 16.1 | 10.7 |

  The selected series is positive in 7/7 months in all four. On res/actual the selector holds
  `G_50pct_net100` from 2026-03 to 2026-08. On res/5% it holds the near-identical `G_100pct_net100`.
  That is why `G_50pct_net100` is recommended: the walk-forward procedure picked it, not a
  full-sample ranking.
- **Deflated Sharpe** (Bailey and López de Prado, N = 52 trials, res, actual fee). The recommended
  policy's daily SR is 0.88 against a max-of-N null of 0.36, so DSR ≈ 1.00. **The baseline fails
  (DSR = 0.21).**
- **Menu-design caveat.** The menu grew in three rounds. F9–F12 were added after round 1. The G
  (net-cap × scale) grid was added after round 2, following a 4-point probe of net caps on F10. The
  meta-selection protects against picking the best item on a fixed menu. It does not protect against
  adding menu items with hindsight. The net cap has an ex-ante reason: prices are calibrated (H2), so
  resolution P&L is noise. But the specific N grid was chosen after seeing the C4–C6 results.

## 6. Capacity (`out/scale_curve.csv`, `fig_frontier.png`)

Figures are for the 1 s/5% period, scaled to 30 days, with walk-forward rules.

| Policy | Capital | Notional / 30 d | res P&L / 30 d | m30 P&L / 30 d | Sharpe, all months |
|---|---|---|---|---|---|
| **Recommended**: R ≈ $100, N = 100 | $23k | $259k | $4.6k | $4.0k | 16.8 |
| R ≈ $100, N = 250 (`G_50pct_net250`) | $34k | $426k | $6.7k | $6.8k | 13.9 |
| $ mirror + wallet + zone, N = 250 (`G_100pct_net250`) | $38k | $461k | $7.3k | $7.1k | 13.6 |
| $ mirror + wallet + zone, N = 2000 (`F12`) | $79k | $1.10M | $32.7k | $19.7k | 6.6 |
| Baseline | $102k | $1.65M | $80.3k | $21.0k | 6.0 |

At a given Sharpe, capacity is bounded by the fast tier's own prints, because we take at most their
size. Raising R stops helping once N binds: G_100pct_net100, where R does not bind, ≈
G_50pct_net100. To deploy more you must accept more net exposure, and Sharpe falls along the
frontier. On the 30 s measure, every one of
these books earns roughly the same 140–170% of its own capital over 7 months (`fig_cum.png`). The
differences in res are resolution noise.

## 7. Recommended policy (concrete)

For each fast-tier print, meaning a wallet qualified on months < m with a print 0–3 s after the
score event, as in H6:

1. **Wallet gate.** Trade only if the wallet's shrunk past 0–3 s gross 30 s markout beats today's fee
   at this price:

   `(Σ mo30_w + 200 · pool) / (n_w + 200) > rate · q(1−q)`

   Here pool is the mean markout of all takers' 0–3 s prints before month m, and rate is today's
   0.05.
2. **Price zone.** Skip tokens with q < 0.05 or q > 0.95.
3. **Size.** Take `shares = min(their print, R/√(q(1−q)), $1000/q)` with **R ≈ $100**. R is refitted
   monthly so the training-period mean ticket equals 50% of the baseline's; it was $98–101 in Jul–Aug.
   - At q = 0.5 that is at most 200 shares, or $100.
   - At q = 0.1 it is at most 338 shares ($34). At q = 0.9 it is 338 shares ($304).
4. **Per match.** Keep |net outcome-0 shares| ≤ **100**: risk-reducing trades are always taken, and
   risk-increasing ones are clipped. Gross per match stays ≤ $3k and per trade ≤ $1k; neither binds.
5. **Exit and stops.** Hold to resolution; a taker exit loses at 5%. No daily stop is needed, since
   the worst day was −2.1% of capital. An operational kill switch belongs in the execution layer and
   was not tested here.
6. **Capital and scaling.** Use 3× peak locked ≈ **$23k**. To scale, keep R ≈ $100 and raise N to
   250 (`G_50pct_net250`): capital ≈ $34k, Sharpe 13.9, max DD −9.7%, worst match −$324, about 1.6×
   the dollars ($70.6k against $43.3k over 7 months; $6.7k against $4.6k per 30 days at 1 s/5%).
   Re-check per-share m30 weekly. The NOTE's rule of halving below 0.3¢ and stopping at ≤ 0 still
   applies.

## 8. Caveats

- **The shadow book is the prize for fast-tier speed, not a copy-trading strategy.** Copying 3 s
  later loses. Every number assumes we fill their print at their price, displacing them. This is not
  remotely executable.
- **The current regime is thin.** 1 s/5% covers only 46 IS days (Jul 11 – Aug 25, 2,167 matches), and
  the per-share edge is trending down month by month. Nothing here has been checked OOS. This lens
  never touched OOS, and the policy should be evaluated once on the locked set by the orchestrator.
- **The m30 mid is a proxy.** It is the mean of the latest bid- and ask-side prints within 30 s, not a
  recorded book. m30 also assumes a free exit, and the taker exit (m30x) is negative at 5%.
- **The 0–3 s opportunity set is defined ex post.** The jump detector confirms up to 10 s after the
  onset, which is inherited from H6. Features that interact with that definition (fill_move,
  pre_move, n_prior3, clip_k, spread0) were excluded after the placebo tests. The q, size, wallet and
  cap rules do not depend on it.
- **Capital is conservative and the bootstrap is approximate.** Capital is gross locked dollars; the
  net cap would let opposite legs be merged, so true capital is lower. Match-cluster bootstrap CIs
  ignore cross-match correlation within a day.
- **Two variant families use within-month fee knowledge.** In fee_mode = actual, the WF zone choice
  (B1/F1/F3) and the Kelly normalisation use the test month's maximum fee rate. That rate is published
  per market. The recommended policy does not depend on it.
- **The Jul–Aug wallet filter keeps most of the tier.** It passes 70 of 72 tier wallets; the gain
  comes from dropping a few high-volume wallets that are negative after the fee.

## 9. Variant count

- 55 named policies: 52 clean plus 3 window-contaminated.
- 16-point zone grid inside 3 policies and a 5-point fill grid inside 1 policy, giving **108
  configurations**. Adding 3 superseded full-deployment smoke tests (share, risk parity and Kelly at
  100%, all identical to the baseline) gives **111**.
- Each policy was scored under 2 P&L measures × 2 fee modes, plus the taker-exit measure for 7
  policies: 234 runs.
- The descriptive tables and the 2 placebo scripts are not variants.

## 10. Reproduce (from the repo root; IS only; ~4 min with 2 processes)

```
.venv/bin/python research/v2/sizing/reproduce.py          # everything below, in order
.venv/bin/python research/v2/sizing/features.py           # data/v2_sizing/features.parquet
.venv/bin/python research/v2/sizing/explore.py            # out/edge_by_*.csv (descriptive)
.venv/bin/python research/v2/sizing/mech_check.py         # out/mech_check.csv (slow-taker placebo)
.venv/bin/python research/v2/sizing/allbucket_check.py    # out/allbucket_check.csv (outside-window placebo)
.venv/bin/python research/v2/sizing/walkforward.py        # out/policies|monthly|regime|meta|deflated_sharpe.csv
.venv/bin/python research/v2/sizing/report.py             # out/recommended_*, scale_curve, noise, match_tails, figs, results.json
```

A from-scratch rerun reproduced every one of the 234 policy rows exactly: max |ΔP&L| = 0 and
max |ΔSharpe| = 0.
