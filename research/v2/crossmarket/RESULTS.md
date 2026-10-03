# Lens "crossmarket": side markets vs the moneyline (in-sample only)

**Question.** After a point, market makers reprice the deep moneyline first. Do the same match's side
markets (set winner, set/game handicap, match/set/first-set totals) stay stale long enough for a remote
trader to take them, using only the moneyline's own move from the public feed?

**Answer.**
1. **Taking stale side quotes (the lens as stated) does not work.** At the first side prints a remote
   taker can reach (detection + delay + 1 s), the median side price already contains 97% of the
   model-implied move. The walk-forward taker book makes +0.93c/share (95% CI −2.8 to +4.7) and $472
   over six months. It deploys about $1.8k notional per 30 days in the current regime.
2. **The moneyline's direction still sorts side-market flow.** Side takers who trade against the
   moneyline-implied move lose 2–9c/share net in every time bucket, and takers who trade with it make
   0–4c. A maker who quotes only on the side that gains from the move gets filled by the losing
   (contrary) flow. Walk-forward, that book makes **+2.73c/share (CI 1.73 to 3.70), 8,905 fills, $4,162,
   Sharpe 2.5**, positive per share in 7 of 7 months (5 of 7 in dollars). In the current 1 s / 5%
   regime it makes **+2.02c/share (CI 0.53 to 3.48)**. Placebos: an unconditional maker makes +0.10c, and
   a maker leaning the wrong way loses −1.83c.
3. **Capacity is tiny.** In-play side-market volume is 1.4–1.9% of the moneyline's ($1.9–2.7M per
   month in Jun–Aug 2026). In the current regime the leaning maker deploys about **$35k notional and makes
   about $2.1k per 30 days** (realized), assuming a 20% queue share. The expected value is about $1.3k at
   3.6% per dollar. Even taking 100% of the contrary flow caps it near $159k notional per 30 days (about
   $6–10k of P&L). This is a side dish next to the moneyline book. It
   cannot be a primary strategy.

The leaning-maker idea came from the step-4 event study, which uses all IS months. So the idea itself is
in-sample. Its window and threshold were then chosen walk-forward (past months only), but only an
out-of-sample test can confirm it. That test is not run here, by rule.

All numbers are IS (matches starting before 2026-08-25 14:15 UTC). No OOS match, `data/locked/`, or live
recording was read.

---

## 1. Data (steps 1–2)

| item | count |
|---|---|
| IS matches (universe_is) | 10,467 |
| Gamma events fetched (batched by id, 50/request, sequential) | 10,467 |
| non-moneyline markets in those events | 107,401 |
| side markets with lifetime volume ≥ $250 (95.3% of side volume), tapes fetched | 30,376 (0 failures) |
| matches with ≥ 1 side tape | 7,000 |
| in-play side taker prints (completed-match market excluded) | 312,558 |
| consecutive-print intervals ≤ 300 s (beta sample) | 225,484 |

Tapes: public data-api `/trades`, at most 4 concurrent requests, exponential back-off on 429/5xx, cached
in `data/v2_crossmarket/trades/`. Side markets first carry volume in Nov 2025. Most months start in Jan 2026.

### Capacity by side-market type (all IS)

| type | markets | lifetime $ | in-play prints | in-play $ | median print $ | p90 print $ | matches | in-play share |
|---|---|---|---|---|---|---|---|---|
| first_set_winner | 9,630 | 14.57M | 95,512 | 6.73M | 9.1 | 145 | 5,178 | 46% |
| set_handicap (±1.5 sets) | 9,900 | 23.45M | 56,391 | 4.94M | 10.0 | 159 | 3,264 | 21% |
| first_set_totals | 28,968 | 11.79M | 42,551 | 4.56M | 17.0 | 210 | 2,950 | 39% |
| match_totals (games O/U) | 28,958 | 15.40M | 54,801 | 4.36M | 9.8 | 142 | 3,655 | 28% |
| set_totals (sets O/U 2.5) | 9,926 | 10.17M | 48,095 | 3.34M | 7.5 | 112 | 3,077 | 33% |
| set_winner (set 2) | 3,622 | 2.21M | 14,761 | 0.98M | 7.3 | 113 | 797 | 45% |
| set_games_totals | 10,868 | 0.14M | 412 | 0.01M | 9.9 | 100 | 42 | 10% |
| game_handicap | 110 | 0.03M | 35 | 0.002M | 10.0 | 182 | 8 | 6% |

### Side vs moneyline in-play volume by month

| month | side in-play $ | moneyline in-play $ | side / ML |
|---|---|---|---|
| 2026-01 | 6.16M | 37.8M | 16.3% |
| 2026-02 | 3.58M | 57.4M | 6.2% |
| 2026-03 | 1.17M | 26.5M | 4.4% |
| 2026-04 | 4.00M | 138.4M | 2.9% |
| 2026-05 | 2.65M | 153.1M | 1.7% |
| 2026-06 | 2.01M | 104.4M | 1.9% |
| 2026-07 | 2.70M | 139.8M | 1.9% |
| 2026-08 (to 08-25) | 1.93M | 140.6M | 1.4% |

Side markets are a thin retail venue. The median in-play print is about $10, and the side share of
in-play volume has fallen as the moneyline grew.

## 2. Sensitivity to the moneyline (step 3), walk-forward

`model.py`. For player markets, the side outcome naming moneyline player 0 moves in log-odds:
d logit(q′) = b · d logit(p). Outcomes are aligned by name, with 99.96% matched. For totals, "Over" is
driven by closeness: d logit(q_over) = b · d[4p(1−p)]. b is OLS through the origin, pooled by type, fit on
months < m only. A second candidate is an **in-match** b, shrunk to the type b with λ ∈ {0.05, 0.25, 1.0}
and using only this match's earlier intervals. The model used in month m is the one with the best pooled
predictive R² on months < m. The pick was local λ=1.0 from Mar 2026 (local λ=0.05 in Feb).

Walk-forward b (Aug 2026 row, fit on Nov–Jul) and month-m predictive correlation:
first_set_winner b=1.53 (corr 0.75), set_winner 1.08 (0.70), set_handicap 0.82 (0.46),
set_totals 2.72 (0.42), match_totals 1.82 (0.34), first_set_totals 3.51 (≈0). Pooled month-m R²
(vs a zero forecast) is 0.20–0.44, rising over time (`beta_model_r2_by_month.csv`, `beta_walkforward.csv`).
b is stable month to month. First-set totals barely follow the moneyline.

## 3. Event study (step 4)

The implied direction of a side print is the sign of the model-implied move. That move runs from the side
market's mid proxy before the jump onset to the moneyline mid at the print. Prints are bucketed by
seconds since detection. The table uses |implied| ≥ 1c, a reference ≤ 600 s old, and months Feb–Aug 2026.
Markout is to resolution, net of each market's taker fee, with cluster-bootstrap 95% CIs by match.

| bucket after detection | implied-direction takers c/share [CI] (n) | contrary takers c/share [CI] (n) |
|---|---|---|
| all in-play side takers | −0.57 [−0.91, −0.22] (250,380) | |
| 1–3 s | +4.41 [−1.67, 11.13] (374) | −9.12 [−17.12, −0.61] (132) |
| 3–6 s | +1.08 [−2.45, 4.74] (1,300) | −6.86 [−10.60, −3.07] (700) |
| 6–10 s | +2.84 [−0.39, 5.87] (1,406) | −4.33 [−7.81, −1.04] (984) |
| 10–20 s | −0.21 [−2.65, 2.30] (2,706) | −5.49 [−8.45, −2.44] (1,873) |
| 20–60 s | +2.01 [0.51, 3.61] (11,644) | −2.70 [−4.60, −0.87] (7,971) |
| 60–300 s | −0.10 [−1.89, 1.49] (21,018) | −1.95 [−3.53, −0.26] (16,298) |
| > 300 s | +1.88 [−0.10, 3.68] (17,657) | −3.28 [−5.69, −1.02] (14,665) |

The delay+1..60 s window by regime (implied / contrary): 3s/0% +1.34 / −5.67; 3s/3% +2.63 / −2.59;
1s/3% +1.23 / −0.29; **1s/5% +1.54 [−0.86, 3.95] / −4.84 [−6.72, −2.97]**.

**Catch-up.** This is the median share of the model-implied move already in the side mid at side prints
in each bucket (`catchup.csv`). It is 0.97 at 1–3 s, 0.93 at 3–6 s, 0.99 at 6–10 s and 0.95 at 10–20 s.
It then drifts to 1.10 at 20–60 s and 1.24 at 60–300 s. So by the first moment a remote taker can execute,
the side market has priced the jump: all of the model move, or about 78% of its level 1–5 minutes later.
What remains is slow drift and contrary flow, not a stale quote waiting to be lifted.

**Who takes the early stale quotes** (delay+1 to 10 s, implied direction): the moneyline fast-tier wallets,
selected walk-forward with `src.fasttier.qualify` on months < m. They make **+7.97c [3.87, 12.06]** on 534
prints ($42k over seven months). Everyone else makes +1.10c [−1.53, 3.64] on 2,546 prints. The seconds-scale
cross-market edge exists, but it belongs to the same sub-second tier, and its total size is tens of
thousands of dollars per year.

## 4. Backtest of the stated lens (step 5): stale-quote taker

Rule (`analyze.py: candidates/trades`):
- After a detection, send marketable orders from detection + 1 s to + 31 s.
- An order sent at t fills against the first side print at ≥ t + delay on our side (an outcome-0 buy needs a
  print that lifted outcome 0's ask).
- Two conditions must hold. First, the side's move since its last print before t is < k × |implied move|.
  Second, |implied| ≥ min_impl. The implied move is the side mid at its last print before t, moved by the
  moneyline's change from that print to t, all strictly before t.
- One entry per side market per jump. Size min($1,000, 50% of the print). At most $3,000 per match. Per-match
  fee.
- Grid: k ∈ {0, 0.25, 0.5, 0.75, 1} × min_impl ∈ {1, 2, 4c}, chosen each month by maximum past cumulative
  $ P&L (months < m, ≥ 30 trades).

| exit | n | c/share [CI] | $ P&L | Sharpe | months $>0 |
|---|---|---|---|---|---|
| hold to resolution (primary) | 675 | +0.93 [−2.81, 4.67] | +472 | 0.77 | 5/6 |
| taker exit at +60 s | 675 | +1.28 [−0.97, 3.64] | −124 | −0.46 | 3/6 |
| passive exit at the implied price | 675 | −6.78 [−9.25, −4.33] | −797 | −1.91 | 3/6 |

Monthly (resolution): Mar +9.6c/$208; Apr +2.8c/$179; May −5.0c/−$702; Jun +4.8c/$224; Jul +3.3c/$265;
Aug −1.3c/$297. Notional is only $0.5–3.6k per month.

By regime: 3s/0% +1.37c (n=26); 3s/3% +3.25c (n=332); 1s/3% −4.90c (n=125); **1s/5% +0.65c [−6.0, 7.2]
(n=192, $539)**. In the current regime it deploys about $1.8k notional and makes about $350 per 30 days.

Other variants:
- Walk-forward type filter on top: −2.31c [−6.7, 2.0], −$28.
- Fixed k=1, min_impl=2c in 1s/5% (reference, not chosen): +1.87c [−2.4, 6.0], $213.
- All 45 grid cells over the evaluation months are in `backtest_grid_all_cells.csv`. Per share they range
  from −3.1 to +2.2c, and none is significant.

The passive exit fails through adverse selection. It is filled when we were right by a little, and it leaves
us holding the losers.

**Verdict on the stated lens:** no tradable staleness for a remote taker after the venue delay. Fills are
rare, and the edge is indistinguishable from zero after the 5% fee.

## 5. Exploratory variants (formed after seeing step 4)

### 5a. Symmetric maker quoting at the model fair ± h. Fails, and the test is uninformative
- Quote both sides at fair ± h, h ∈ {0, 1, 2c}, always-on or for 60 s after a jump.
- Fill at our own price whenever a print traded through it. 20% of the print, ≤ $250 per fill, ≤ $2k per
  match.
- Result: −5.1 to −7.4c/share in every cell. Walk-forward: −7.39c [−8.40, −6.48].

The tape-based fair (a stale side mid proxy carried forward by the moneyline) is not precise enough to quote
inside the real side spread. Quoting at it hands the spread to takers. Without historical books this variant
cannot be fixed.

### 5b. Leaning maker. Best variant
Rule (`analyze.py: lean_maker`):
- Compute the implied side move from information strictly before (print time − delay). That is the side
  market's last print mid and the moneyline mid then and now, with the walk-forward b.
- When |implied| ≥ min_impl, rest only on the side that gains: a bid on outcome 0 if the implied move is up,
  an offer if it is down.
- We are filled only by takers trading against the implied move, at the print price (we joined that level).
  20% of each such print, ≤ $250 per fill, ≤ $2,000 per match.
- Hold to resolution. Makers pay no fee and receive the 15% rebate.
- Grid: window ∈ {always-on, 60 s after a jump} × min_impl ∈ {1, 2, 4c}, chosen monthly by past $ P&L.
  Choices: Feb post-jump/4c, Mar always/1c, Apr post-jump/2c, May–Aug always/4c.

| | n | c/share [CI] | $ P&L | notional | Sharpe | max DD |
|---|---|---|---|---|---|---|
| walk-forward, Feb–Aug 2026 | 8,905 fills / 2,556 matches | **+2.73 [1.73, 3.70]** (share-weighted +2.59) | **+4,162** | $87k | 2.49 | −44% of 3× peak locked ($2.8k) |

Monthly: Feb +8.9c/$250; Mar +2.1c/−$561; Apr +3.3c/−$187; May +2.3c/$535; Jun +4.2c/$801; Jul +0.6c/$330;
Aug +3.2c/$2,993. That is 7/7 months positive per share and 5/7 in dollars. Hit rate 58%.

By regime: 3s/0% +5.54c [2.52, 8.61]; 3s/3% +2.92c [0.57, 5.40]; 1s/3% +2.56c [0.32, 4.88];
**1s/5% +2.02c [0.53, 3.48]** (n=4,159, $3,269 over 46 days, Jul 11–Aug 25).

By type (c/share): first_set_winner +2.23 [0.92, 3.54] (59% of fills); set_handicap +4.64 [1.65, 7.59];
match_totals +5.36 [0.55, 9.96]; set_totals +3.91 [0.41, 7.31]; set_winner +1.22 [−1.46, 4.12].

Diagnostics on the same fill model, Feb–Aug, always-on (`lean_maker.diagnostics`):

| book | all regimes c/share [CI] | 1s/5% c/share [CI] | flow $/month |
|---|---|---|---|
| unconditional maker (every print, both sides) | +0.10 [−0.45, 0.65] | −0.12 [−1.26, 0.95] | 891k |
| anti-lean placebo (filled by implied-direction takers, |impl| ≥ 4c) | −1.83 [−2.64, −1.01] | −1.29 [−2.75, 0.12] | 109k |
| lean (|impl| ≥ 4c) | +3.06 [2.11, 4.01] | +2.02 [0.53, 3.48] | 62k |

Economics: price discovery happens in the deep moneyline. Thin side markets, mostly $10 retail tickets,
under-react, and part of their flow trades against the moneyline's news. A maker can stand only in the way of
that flow, at zero fee. Hold-to-resolution variance makes the dollar series noisy. The −$561 month is
per-share positive.

**Remote-executable:** yes. It needs the public moneyline feed plus quoting in side markets. Makers can cancel
instantly (no order delay). The edge is not confined to the first seconds (the always-on window is chosen), so
sub-second speed is not needed.

## 6. Variants tried: 68 (every one listed in `analysis.json["variants"]`)
- Beta models: 5. Logit type-level; linear diagnostic; in-match λ ∈ {0.05, 0.25, 1.0}.
- Event study: 2 (min_impl 1c and 2c).
- Stale-quote taker: 15 grid cells × 3 exits = 45, plus the walk-forward type filter = 1.
- Symmetric maker: 6.
- Leaning-maker diagnostics: 3.
- Leaning maker: 6.

The pipeline was also debug-run on partial data (Jul–Aug 2026 tapes as they arrived) with the same code and
grids. Those runs showed August results for the walk-forward picks. No rule or constant was changed because of
them.

Fixed a priori, not tuned:
- our latency 1 s; send window 30 s
- side reference ≤ 600 s old
- mid proxies: latest bid- and ask-side prints ≤ 120 s old (side) and ≤ 30 s old (moneyline)
- taker sizing: $1k, 50% of the print, $3k per match
- maker sizing: 20% of the print, $250 per fill, $2k per match
- the jump detector (jumps_is)

## 7. Caveats
- **Fill model (most important).** There are no historical books. The maker assumes we were at the printed
  level and got 20% of each contrary print. Queue position, joining after the move, and our own effect on side
  prices are not modelled. Live side books (median spread unknown here; moneyline median 1c) would be needed to
  validate this. The OOS-period live recordings are off-limits for this lens.
- **Post-hoc hypothesis.** The leaning maker was formed after the step-4 event study on all IS months. Its
  parameters are walk-forward, but the idea is IS-generated. Only OOS can test it.
- **Tiny capacity.** About $35k notional and $1.3–2.1k P&L (expected–realized) per 30 days in the current
  regime at a 20% queue share. The ceiling is about $159k notional per 30 days at 100% of contrary flow (3.6–6%
  return per dollar). Side-market share of
  in-play volume is shrinking (16% → 1.4%).
- **Hold-to-resolution variance.** The worst day is −24% of the small capital base, and dollar months are
  negative in 2 of 7 despite positive per-share edge.
- Trade timestamps are 1 s, on-chain block time. Moneyline information is taken strictly before t_send and
  side references strictly before t_send. Same-second ordering is unknown, so this is conservative for the
  taker and the maker.
- Markets with lifetime volume < $250 (4.7% of side volume) were not fetched. Completed-match markets were
  excluded.
- The model fair is crude (R² 0.2–0.4). Better state models (score feed plus the Markov model) could sharpen
  the lean, but the Polymarket score feed lags about 55 s.

## 8. Reproduce (from the repo root)
```bash
.venv/bin/python research/v2/crossmarket/fetch_events.py   # Gamma catalogue -> data/v2_crossmarket/side_markets.parquet (~2 min)
.venv/bin/python research/v2/crossmarket/fetch_tapes.py    # 30,376 side tapes, <=4 concurrent (~35 min, cached)
.venv/bin/python research/v2/crossmarket/build.py          # per-print tables (~2.5 min, 2 workers)
.venv/bin/python research/v2/crossmarket/analyze.py        # steps 2-5 + variants -> analysis.json, CSVs (~15 s)
.venv/bin/python research/v2/crossmarket/report.py         # figures, tables.md, results.json
```
Outputs:
- `results.json` (headline numbers)
- `analysis.json` (everything)
- `tables.md` (all tables)
- `fig_event_study.png`, `fig_lean_maker.png`, `fig_wf_monthly.png`
- CSVs: capacity, beta, event study, catch-up, grid, walk-forward choices
- trade-level books in `data/v2_crossmarket/wf_*.parquet`
