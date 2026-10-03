# COURTSIDE: who gets paid in the seconds after a tennis point

*Gator Quant Hacks 2026, Systematic Trading. Repo: `<GITHUB_URL>`. One command: `python run_all.py --oos`.*

## 1. Economic foundation

A tennis point ends in tiers. Ball tracking knows the landing point while the ball is still in
the air. The umpire knows at the bounce. Official data feeds, and the market makers that consume
them, know one to a few seconds later. TV knows a few seconds after that. Streams and score
widgets know tens of seconds later. In-play match-win probability is a known function of the
score (we built the exact point-level Markov chain, `src/markov.py`), so every point moves fair
value by a computable amount, its **leverage**. A typical ATP best-of-3 match has ~161 points with
mean |leverage| 5.7%. Fair value travels 4.2 full dollars per share over the match, and the ten
biggest points carry ~23% of that.

**Who is on the other side?** Anyone acting on an older tier. A trader who knows the point outcome
before the book reprices buys the stale side from a resting order. A trader who acts after the book
reprices pays the spread to someone faster. The tier gap is physical (stream delays, camera frame
rates, data-licensing latency), so it doesn't arbitrage away. Polymarket shows it knows this:
sports markets hold every marketable order for 1–3 s (`secondsDelay`) to protect makers.

Hypotheses were written and committed before any result (`HYPOTHESIS.md`, commit `7232986`). Every
later change is in `DEVIATIONS.md`.

## 2. Data

- **Every resolved ATP/WTA singles moneyline on Polymarket with ≥$5k volume, Oct 2025–Oct 2026:
  13,084 matches, $2.84B traded.** Full taker trade tapes (13,081 matches) from the public data
  API, with second timestamps and wallets. Each print is classified as hitting the bid or lifting
  the ask (buying one outcome = selling the other), so we pay historical spreads, not assumed ones.
- Each match's own fee (`0.05·p(1−p)` per share today; 0 or 0.03 earlier) and delay (3 s → 1 s in
  May 2026).
- **Out-of-sample:** the last 20% of matches (from 2026-08-25, n = 2,617), locked until all rules
  were frozen (commit `9d61d1b`) and evaluated once (`results/oos_peeks.log`).
- **Live:** our recorder logged Polymarket's order books and its public sports score feed side by
  side, with millisecond receive times, for every tennis and table-tennis market on 2026-10-03.
- **Ball tracking:** OpenTTGames (120 fps table tennis, labeled bounces) and a tennis broadcast
  dataset, run on HiPerGator, plus a physics Monte Carlo of Hawk-Eye-class tracking.

## 3. What failed (reported in full)

| Hypothesis (pre-registered) | In-sample result, net of fees and spread | Verdict |
|---|---|---|
| H1 follow the jump after the delay | −1.50 to −1.86¢/share in all 20 variants; CIs exclude 0 | Fails |
| H2 favourite-band calibration edge | All 6 variants' CIs include 0; prices calibrated within ~1¢ | Fails |
| H5 maker quoting after jumps (post-hoc) | +0.22¢ (CI −0.01…0.43) vs always-on +0.13¢ | Weak, see OOS |

Copying the market's direction after a score event is the most intuitive "speed" trade, and it
loses: by the time a delayed order fills, the book has moved and you pay the spread to whoever
moved it.

## 4. The finding: a persistent fast tier

Bucket every taker print by seconds since the latest score event (jump onset) and mark it out 30 s
later, net of fee (Fig. 1). **Takers as a whole lose about 1¢/share in every bucket.** A small set
of wallets does the opposite, and does it best in the first 3 s.

*H6 (post-hoc, so only the walk-forward and OOS results count):* each month, select wallets using
only earlier months (≥30 prints within 3 s of a score event, ≥10 matches, t > 3 on 30 s markout).
Score their next-month prints in that window, net of fee.

- In sample, **positive in 9 of 9 months**, +0.6 to +2.4¢/share. The other takers in the same window
  were negative in 9 of 9.
- **Copying them** with a 3 s lag is negative in 9 of 9 months. The edge is speed, not a signal
  anyone can follow.
- Shadow book (what a trader at that speed earns: their trades, ≤$1k each, ≤$3k per match, held to
  resolution, net of fees). In sample: **+1.16¢/share (CI 0.79–1.54), 131k trades in 8,514
  matches, Sharpe 5.5, worst month −$771.** OOS: `[OOS_SHADOW]`.
- The edge is shrinking: 1.5–1.6¢ under the 3 s delay, 1.19¢ at 1 s/3% fees, **0.54¢ at today's
  1 s/5%**. Qualifying wallets went from 4 to 101.

The Sharpe is high because this is ~520 small, independent bets a day, close to a market-making
P&L profile. After 44 disclosed backtest variants, the expected best Sharpe from luck alone is ~2.7
(Bailey & López de Prado). The OOS result is the real test.

## 5. How ball tracking gets you into the fast tier

- **Physics (tennis, Hawk-Eye-class 340 fps, 3.6 mm noise):** landing-point error is ±0.7 cm 25 ms
  before the bounce, ±2.4 cm at 100 ms, ±5.8 cm at 200 ms, ±10.7 cm at 300 ms. A ball landing ≥4 cm
  out is called with 95% confidence 100 ms early; one ≥18 cm out, 300 ms early (Fig. 4).
- **Table tennis on real 120 fps video:** `[TT_RESULT]`.
- **Tennis broadcast video:** `[TENNIS_VIDEO_RESULT]`.
- **The public score feed is the slowest tier (H4, live):** the book moved first on 92% of score
  changes, a median 45 s ahead of Polymarket's own sports feed (n = 38 on 2026-10-03). The feed
  sends ~32 s snapshots. Anyone trading off it is the "others" bar in Fig. 1.

**The strategy (COURTSIDE).** At every point, the Markov model gives the fair-value jump riding on
it (leverage × P(call)). When ball tracking calls the point before it lands, send a marketable order
for the side the point favours, if `leverage × P(correct) − fee − ½ spread > 0`. Size by leverage and
by visible depth. Hold to resolution, or exit into the post-point flow. The tracking lead (100–300
ms) stacks on top of a low-latency official feed; it does not replace it. Remote traders on
broadcast video are tier 4.

## 6. Risk management

- **Venue rule risk (the largest):** the edge fell by ~2/3 when fees rose to 5%. A longer delay
  would cut it further. Rule: re-estimate net edge weekly on the trailing month's fast-tier
  markouts; halve size if it is below 0.3¢, stop if it is below 0.
- **Speed race:** qualifying wallets rose 4 → 101. If our measured fill-to-reprice latency
  (logged live) degrades, size scales down linearly.
- **Wrong call:** a mis-called point loses its leverage. Trade only calls with P(correct) ≥ 0.95,
  and only when the call margin exceeds the 95% callable margin for the current lead (Fig. 4).
- **Limits:** ≤$1k per order, ≤$3k per match, capital = 3× the peak dollars locked. Daily stop at
  −5% of capital. Kill switch on any feed or tracking dropout > 2 s.
- **Resolution risk:** 2.9% of matches resolved 50/50 (retirements, walkovers). Hold-to-resolution
  P&L already includes them.
- **Legal and access:** courtsiding breaks most tournaments' ticket terms (ejection), and live
  tracking data is licensed. Polymarket's international venue restricts US persons (these events
  are flagged `restricted`). A real deployment means licensed low-latency data, a permitted
  venue/jurisdiction, and legal review. This repo only reads public data; it never places orders.

## 7. Liquidity and capital

- Tennis books are deep: in the live sample, median 1¢ spread, $8.1k at the touch, $61k within 2¢
  of it. Fast-tier volume in the 0–3 s window ran $0.3–2.7M a month in sample.
- **Table tennis is not tradable on Polymarket:** median 89¢ spread, $23 at the touch, 25% empty
  books, ~$2 of volume per match. The big table-tennis price swings people see are midpoints of
  near-empty books.
- Capacity: the shadow book at ≤$3k/match deploys ~$11k peak locked capital (`[PEAK]`). Scaling
  past the fast tier's own volume means competing with it for the same stale quotes. We estimate
  practical capacity at $50–150k of capital at today's fee level.

## 8. Variants and caveats

44 strategy variants backtested (H1 20, H2 6, H5 17, H6 1), all reported, plus exploratory
calibration, tier and wallet studies (disclosed in `DEVIATIONS.md`). H5 and H6 were formulated after
looking at in-sample data. The shadow book is an *opportunity* estimate: it assumes our tracker plus
data feed reaches the fast tier's speed, which we have not demonstrated in production.
