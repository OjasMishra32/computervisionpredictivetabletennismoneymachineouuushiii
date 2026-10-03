# Table tennis dataset (TT1–TT5 inputs)

Built 2026-10-03, 18:37–19:09 UTC, after the pre-registration commit `0f01362` (`HYPOTHESIS_TT.md`).
Everything ran locally on the laptop; HiPerGator was not used, because nothing here is CPU-heavy.
Every number below comes from `scripts/tt_fetch.py`, `scripts/tt_build.py` or their outputs. The
only network endpoints were the public gamma-api and data-api; no keys were used and no order was
placed.

This step computed **no price, markout, calibration or P&L statistic**. The liquidity tables hold
counts and volume only, as TT4 describes.

## Commands

```
python scripts/tt_fetch.py catalogue   # gamma walk, all market types -> data/tt/gamma_markets.parquet, research/tt/catalogue_check.json, child_tags.csv
python scripts/tt_fetch.py trades      # UTT tapes -> data/raw/trades/{cond}.parquet, data/tt/fetch_manifest.parquet
python scripts/tt_build.py universe    # data/tt/universe.parquet
python scripts/tt_build.py prints      # data/tt/prints.parquet, data/tt/build_status.parquet
python scripts/tt_build.py liquidity   # research/tt/liquidity.csv, data/tt/market_liquidity.parquet
python scripts/tt_fetch.py zerocheck   # one /trades request per zero-volume moneyline -> data/tt/zero_volume_check.parquet
python scripts/tt_fetch.py unlisted    # full tapes for the zero-volume markets that have fills
python scripts/tt_build.py unlisted    # *_unlisted universe, prints, status and research/tt/liquidity_unlisted.csv
```

`research/tt/build_tt.py` is the entry point named in the pre-registration. It runs `trades`,
`universe` and `prints`. A rerun with every tape cached reproduced `data/tt/prints.parquet` byte for
byte (sha256 `b9edeba0…c879`).

## How the fetch follows the pre-registration

- **Universe.** UTT is built from the cached catalogue
  `data/raw/events_table-tennis_2025-07-01_2026-10-03.parquet`. The code checks that file's sha256
  (`daa48f2c…f8`) before it does anything.
  - `tt_build.universe()` asserts every pre-registered count: 3,588 markets, cut 2026-09-16 05:30 UTC,
    IS 2,870 / OOS 718, league counts, `res0` counts, and the first and last start.
  - All of them match.
- **Tapes** come from `src.polymarket.fetch_trades`, unchanged: same parsing, same cache
  (`data/raw/trades/{cond}.parquet`, compact parquet).
  - The only change is a back-off-only wrapper on its HTTP GET. It allows at most 4 concurrent
    data-api requests and backs off exponentially (1, 2, 4 … 60 s with jitter, honouring
    Retry-After) on 429, 5xx and network errors.
  - A non-list reply is retried instead of being cached as a short tape.
  - The task brief suggested `data/tt/trades/` for the cache. The pre-registration fixes
    `data/raw/trades/`, and `src.tape.load_tape` reads from there, so the tapes went there.
- **Selection rule: every UTT market, no sampling.** The full set took 258 s, so the brief's
  fallback (all WTT/other markets, Setka with volume ≥ $20, and a 20% sample of the rest) was not
  needed.
- **Prints** come from `src.tiers.match_prints` for every UTT row, unchanged, using 3 processes.
  `data/tt/prints.parquet` has exactly the 19 columns and dtypes of `data/is_prints.parquet`.
- **Universe file.** `data/tt/universe.parquet` holds every catalogue column plus `start`, `end`,
  `fee_rate`, `delay`, `oos`, `league` and `month`.

## Counts

### Gamma (metadata), walked 2026-10-03 18:38 UTC
- **Scope.** Tag 103767, `closed=true`, one-day `start_date` windows over the catalogue's window
  (2025-07-01 to 2026-10-03).
- **Totals.** 26,948 closed events and 126,438 markets. No daily window reached gamma's
  2,000-offset cap.
- **Market types.** Every event has exactly one moneyline (match winner), and every moneyline has
  2 outcomes.

  | type | markets | events | with listed volume | listed volume |
  |---|---|---|---|---|
  | moneyline | 26,948 | 26,948 | 3,593 | 1,017,163 |
  | table_tennis_match_totals | 51,152 | 25,576 | 1,834 | 102,388 |
  | table_tennis_game_handicap | 48,338 | 25,575 | 733 | 40,207 |

  - Totals and handicaps exist on Setka, and on 235/234 WTT events from 2026-06-12 (470/468
    markets).
  - Only the moneyline is studied.
- **Child tags** are listed in `research/tt/child_tags.csv`.
  - The children come from gamma `/sports` entries whose tag list contains 103767: wttmen 103773,
    wttwom 103774, WTT 103768, setka 105715, setkameua/memd/mecz/woua 105716–105719, ttelite 105708,
    czechligapro 105709 (not in the brief's list), ttcup, ttchallenger, ttbl, ttcl, tteuropecup,
    ttworldcup, ttworlds and ttolympics.
  - Every closed event of every child tag that falls in the window is in the tag-103767 walk;
    0 are missing.
  - czechligapro, ttcup, ttchallenger, ttbl, ttcl, tteuropecup, ttworldcup, ttworlds and
    ttolympics have 0 closed events. ttelite has 1.
  - The Setka tags hit the 2,000 cap when paged without dates. Their first 2,000 events are all in
    the walk, and the dated walk itself was not capped.
- **Fresh walk vs the cached catalogue.** All 26,764 cached rows are present.
  - Listed volume differs by more than 1¢ on 0 of them.
  - No cached zero-volume row has listed volume now.
  - For UTT rows, `res0`, fee rate and delay are unchanged on all 3,588.
  - 184 events are new: they closed after the catalogue was built (starts 2026-08-18 to 2026-10-03;
    5 have volume). They are not in the study; the catalogue is not refreshed.

### Trade tapes (UTT)

| | Setka | WTT | other | all |
|---|---|---|---|---|
| markets (= events) | 2,706 | 881 | 1 | 3,588 |
| fetched / failed | 2,706 / 0 | 881 / 0 | 1 / 0 | 3,588 / 0 |
| markets with ≥ 1 fill | 2,706 | 881 | 1 | 3,588 |
| fills (taker prints) | 7,767 | 6,137 | 4 | 13,908 |
| fills per market, median / p90 / max | 2 / 6 / 73 | 4 / 14 / 151 | 4 | 2 / 8 / 151 |
| tape USD (Σ size·price) | $248,396 | $404,066 | $5.98 | $652,468 |
| tape USD per market, median / p90 | $9.90 / $99.00 | $162.94 / $830.12 | | $21.04 / $274.41 |
| pre-start USD | $16,610 (6.7%) | $144,596 (35.8%) | $0 | $161,205 |
| in-play window USD (start → close) | $231,787 | $259,470 | $5.98 | $491,262 |
| USD after close | $0 | $0 | $0 | $0 |
| IS / OOS tape USD | $201,650 / $46,746 | $404,066 / – | $5.98 / – | $605,722 / $46,746 |

- **Requests.** 3,665 in total. 77 got HTTP 429 and succeeded on back-off.
- **Offset cap.** No market came near data-api's 10,000-offset cap (max 151 fills). data-api
  returns HTTP 400 past offset 10,000; checked on a tennis market.
- **Completeness.** Gamma's listed `volume` equals the sum of fill sizes on the taker tape: it is in
  **shares, not dollars**. The pre-registration's "$" listed volumes are share counts.
  - The two agree within 1% on 3,535 of 3,588 markets.
  - The other 53 are all WTT (2026-03/04). There the tape holds 50–101.5% of listed shares
    (median 96%; 55,163 vs 59,133 shares in total).

### Prints (`data/tt/prints.parquet`)

| status (`data/tt/build_status.parquet`) | Setka IS | Setka OOS | WTT IS | other IS | all |
|---|---|---|---|---|---|
| ok (≥ 20 in-play prints) | 16 | 3 | 8 | 0 | **27** |
| < 20 in-play prints | 1,970 | 715 | 863 | 1 | 3,549 |
| ≥ 20 in-play prints but no jump (dropped) | 2 | 0 | 10 | 0 | 12 |
| fetch failed / other error | 0 | 0 | 0 | 0 | 0 |
| print rows | 506 | 92 | 404 | 0 | **1,002** |

- **Few in-play prints.** Matches with < 20 in-play prints have a median of 2 (max 19). The 17
  `end <= start` rows are all in that group.
- **No 0.5 matches.** None of the 27 evaluable matches has `res0` = 0.5.
- **Fees and delays of the evaluable matches.**
  - Setka: 19 matches, 5% fee, 1 s delay.
  - WTT: 3 matches with 3 s delay and no fee; 5 with 3 s delay and a 3% fee.
- **No-jump drops.** `tiers.match_prints` raises `IndexError` when a match has ≥ 20 in-play prints
  but `jump_onsets` finds no onset (it indexes an empty onset array).
  - The tennis builders (`src/prints.py`, `scripts/tiers_is.py`) catch this and drop the match.
    Tennis U1 IS lost **527 of 10,467** markets this way; checked here by rerunning the detector on
    the IS markets missing from `data/is_prints.parquet`.
  - The 12 table tennis cases are dropped the same way, but labelled `no_jump`, not silently.
  - The pre-registration did not mention this path. It is the unchanged tennis behaviour, not a
    deviation.

## Unusual: markets with listed volume 0 that did trade (not in UTT)

The pre-registration excluded zero-volume markets because "a market with no fills has no tape".
`zerocheck` tested that claim: one `/trades?limit=1` request for each of the 23,176 zero-volume
moneylines, with 0 errors.
- **96 have fills.** 79 are WTT, all with starts 2026-03-10 to 03-16 and 03-26. That is 79 of the 80
  zero-volume WTT markets in March, essentially a whole WTT event week. The other 17 are Setka
  (Jul–Sep).
- **Missing field.** Gamma omits the market `volume` field for these markets, in the event payload
  and in `/markets?condition_ids=…&closed=true`. The catalogue therefore read them as 0.
- **Their full tapes**, fetched with the same code:

  | | markets | fills | tape USD | pre-start | in-play window | ≥ 20 in-play prints | no jump |
  |---|---|---|---|---|---|---|---|
  | WTT | 79 | 1,397 | $169,280 | $68,087 | $101,193 | 7 | 3 |
  | Setka | 17 | 35 | $373 | $6 | $327 | 0 | 0 |

  - All 96 start before the cut, so all are IS.
  - `res0`: 53 at 0, 40 at 1, 3 at 0.5.
  - The WTT ones have no fee and a 3 s delay.
  - With them, WTT tape USD would be 42% larger.
- **Not merged into UTT.** UTT stays exactly as pre-registered. These markets are kept apart in
  `data/tt/universe_unlisted.parquet`, `prints_unlisted.parquet` (272 rows, 7 matches, same columns),
  `build_status_unlisted.parquet` and `research/tt/liquidity_unlisted.csv`. Their oos flag uses the
  pre-registered cut.
- **Open decision for the test step.** Whether to report a sensitivity run that includes them has to
  be decided, and written in `research/tt/DEVIATIONS.md`, **before** `tt_test.py` runs. Adding them
  to UTT would move the 80% cut, so the pre-registered split cannot simply absorb them.

## Other things worth knowing (metadata unless stated)

- **Fees.** The UTT fee schedules read now (`catalogue_check.json`):
  - Setka and other: rate 0.05, exponent 1, takerOnly, rebateRate **0.15**.
  - WTT from 2026-03-30: rate 0.03, exponent 1, takerOnly, rebateRate **0.25**.
  - The 172 WTT markets before that have no schedule and `feesEnabled = false`, so the fee is 0.
  - Totals and handicaps carry the same rate as their league's moneyline.
  - The legacy `makerBaseFee`/`takerBaseFee` fields read 1000 wherever a schedule exists. The study
    uses `feeSchedule.rate`, as tennis does.
- **Order delay.** `secondsDelay` is 3 s on 579 WTT markets (until 2026-05-10) and 1 s everywhere
  else, including all Setka and every totals/handicap market.
- **Tick.**
  - UTT: 0.001 on 3,115 markets and 0.01 on 473 (Setka 394, WTT 78, other 1). No tick exceeds 0.01,
    so the pre-registered J = 0.04 stands.
  - The minimum order is 5 shares on every market, which is large next to the Setka median of
    2 fills and $9.90 per market.
- **WTT ends 2026-07-06.** That is the last WTT moneyline in the catalogue; Setka starts 2026-07. So
  OOS is all Setka, as pre-registered.
- **Close time.** No fill on any tape is after the market's close time. The in-play window
  (start → close) therefore holds post-match prints but nothing after close.
- **Timestamps.** Integer-second block times, as for tennis.

## Files

| file | committed | sha256 (first 8) |
|---|---|---|
| `scripts/tt_fetch.py`, `scripts/tt_build.py`, `research/tt/build_tt.py` | yes | |
| `research/tt/liquidity.csv` (league × month, plus IS/OOS/ALL rows) | yes | |
| `research/tt/liquidity_unlisted.csv`, `catalogue_check.json`, `child_tags.csv` | yes | |
| `data/tt/universe.parquet` | no (data/) | bef50238 |
| `data/tt/prints.parquet` | no | b9edeba0 |
| `data/tt/build_status.parquet` | no | 71f23731 |
| `data/tt/fetch_manifest.parquet` | no | 4b8891bf |
| `data/tt/market_liquidity.parquet` | no | 47bfa691 |
| `data/tt/gamma_markets.parquet` (all market types, 27.8 MB) | no | 76071a56 |
| `data/tt/zero_volume_check.parquet` | no | 3bc3edd0 |
| `data/tt/universe_unlisted.parquet` / `prints_unlisted.parquet` | no | 77773d36 / ba5098eb |
| `data/raw/trades/{cond}.parquet` (3,684 table tennis tapes) | no | |
| `data/tt/fetch.log` (every fetch run, with HTTP counts) | no | |
