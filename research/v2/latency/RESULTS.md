# Lens "latency": public tennis score sources vs the Polymarket book

**Bottom line: no public score source beats the book. In practice, the Polymarket moneyline is the fastest public score feed.**

On the WTA's official point clock (the umpire-entered timestamp in the WTA point-by-point log), the Polymarket
moneyline reprices a **median 1.2 s before the official point timestamp** (n = 482 points, 9 WTA matches,
p10 -2.9 s, p90 +0.1 s). The fastest public source is the ESPN scoreboard. It reports a game a median
**27.5 s after** the official stamp, which puts it **28.2 s behind the book**. Polymarket's own sports websocket
is 29.1 s after the stamp and 30.0 s behind the book. The WTA's own public JSON API is point-level but
CDN-cached, so it arrives 43 s after the stamp and 44 s behind the book. **Of 295 source-observed score changes
matched to a book reprice, 0 led the book by more than 1.3 s** (1 s venue order delay + 0.3 s). A latency
strategy driven by public data is not executable in the current regime. Whoever moves the book (MMs and the
fast tier) has information at least as fast as the chair umpire's tablet.

All numbers below come from live forward data recorded on 2026-10-03, between 09:46 and 12:45 UTC. That data
was used only to measure latency. Nothing here is tuned, and no in-sample or locked data was read.
Reproduce with:

```
python research/v2/latency/recorder.py --hours 20     # live recorder (runs under nohup, see "Recorders" below)
python research/v2/latency/fetch_pbp.py                # official WTA point-by-point logs for today, cached
python research/v2/latency/analyze.py                  # every number in this file -> out/summary.json, results.json
```

Outputs: `out/summary.json` (all statistics), `results.json` (headline, variants, excluded sources, summary),
`out/m1_points.csv`, `out/m1_source_leads.csv`, `out/m2_source_leads.csv`, `out/cross_market.csv`,
`out/stale_depth.csv`, `out/trades_around_reprice.csv`, `out/latency_ecdf.png`.

## 1. What was recorded

`recorder.py` stamps every record with the local receive time in ms. The local clock is within 0.0 ± 11 ms of
time.apple.com (checked with sntp). It runs four streams on one asyncio loop:

| stream | source | granularity | how |
|---|---|---|---|
| `pmsports_*` | Polymarket sports websocket `wss://sports-api.polymarket.com/ws` | game (set/game score string) | push; tennis leagues only |
| `espn_*` | ESPN `site.api.espn.com/.../tennis/{atp,wta}/scoreboard` | game, plus server | each endpoint polled every 2 s; written on change |
| `wta_*` | WTA public JSON `api.wtatennis.com/tennis` (no key; robots.txt allows all) | **point** (PointA/PointB) + official point log | `tournaments/<id>/<yr>/matches?states=L` every 2 s, `.../matches/<mid>/score` every 4 s, `.../point-by-point` every 15 s |
| `clob_*`, `clobmeta_*` | Polymarket CLOB market websocket | full book (book snapshots, price_change, best_bid_ask, last_trade_price) | **every open market** (moneyline + all 9 side-market types) of tennis events starting within -10 h / +2 h; rediscovered every 120 s; ~1,500 tokens over 4 sockets |

Book records are compacted (asset id -> int, mapped in `clobmeta_*`). Files rotate hourly and are gzipped, which
comes to about 15 MB/h. The moneyline books from the already-running `src/live_recorder.py` (`data/live/market_*`,
since 09:46 UTC) are merged in as a read-only input, so book coverage starts at 09:46. Side-market books start at
11:08. `fetch_pbp.py` pulls the WTA official point-by-point log once per singles match played today and caches it
under `data/v2_latency/pbp/`. This gives an official timestamp for every point, including points from before the
recorder started.

Coverage at analysis time: 2.98 h of moneyline books and 1.56 h of side-market books (both recorders together).
Units observed: ESPN 76 games across 10 matches, PM sports 156 games across 14 matches, WTA API 163 points and
43 games across 6 matches. The official log has 994 points across 9 WTA matches, and 492 of those points fall
inside book coverage.

### Sources probed and excluded (not used)

| source | why excluded |
|---|---|
| atptour.com / app.atptour.com (ATP live scores) | Cloudflare challenge (HTTP 403). Blocks automated access. |
| protennislive.com (official ATP/WTA scoring app) | Cloudflare HTTP 503 to non-browser clients |
| sofascore.com / api.sofascore.com | HTTP 403 even on robots.txt |
| itftennis.com | Imperva bot-protection JS challenge |
| livescore.com public API | robots.txt disallows `/api/` |
| flashscore | ToS prohibits automated extraction; obfuscated feed |
| gamma-api.polymarket.com event `score` (REST) | Tested: Cloudflare-cached (max-age 300, purged on change). In the one change observed it was ~6 s behind the sports websocket. Not recorded. |

Nothing was fetched with a login, key or payment, and no bot protection was bypassed. The WTA page embeds an
API key, which was **not** used; the endpoints above answer without it. That leaves no public point-level source
for ATP or Challenger matches. For those, only ESPN and PM sports (both game-level) are available.

## 2. Method

A **unit** is a score change that hands a point or a game to one player. Each source's state is oriented to the
Polymarket moneyline (outcome 0) by name matching. A unit's direction is +1 when the outcome-0 player won it.
Ambiguous jumps are dropped: two or more games at once, or point states that cannot be ordered. So are changes
first seen within 60 s (push) or 10 s (polled) after a recording outage, because they are late by construction
(3 dropped). Reprice times use the outcome-0 mid, counting only quotes with spread <= 5c (10c for side markets).

* **M1, official clock (WTA matches, primary).** For each official point at time T_p, the book reprice is the
  time the mid first crosses half of its net move toward the point winner, inside
  [T_p - min(10 s, gap_prev/2), T_p + min(25 s, gap_next - 4 s)]. The move must be at least 1 tick. "First tick"
  is the first crossing of 1 tick. The -4 s trims the window so it does not catch the book's anticipation of the
  next point. Each source observation of that point (WTA API), or of the game the point ended (ESPN, PM sports),
  gets `lead = t_book - t_source` and `delay = t_source - T_p`.
  **Placebo / orientation check:** inside these windows the median maximum excursion is 3.0c toward the point
  winner and 0.0c toward the loser. The net move goes toward the winner in 96.3% of points and toward the loser
  in 1.6%. Book coverage: 96.3% of covered points show a reprice of at least 1 tick. Every ESPN, PM and WTA unit
  agrees with the official winner (100%).
* **M2, source clock (every match, including ATP and Challenger).** Find the biggest move in the implied
  direction over a 3 s horizon inside [t_s - 90 s, t_s + 30 s], then take the half-move onset. This is the
  "biggest move in [-90 s, +30 s]" rule. It is biased: the 90 s window spans several points, so it often picks an
  earlier, larger point (for example a break point). M2 is reported as a robustness view only.

## 3. Results: lead/lag per source (current regime: 1 s delay, 5% fee; all data from one day)

### 3a. Official clock (M1)

| quantity | n | median | p10 | p90 | share > +1.3 s |
|---|---|---|---|---|---|
| **Polymarket book reprice - T_p** (half-move) | 482 | **-1.16 s** | -2.93 | +0.08 | 3.7% |
| book, first 1-tick move - T_p | 482 | -1.73 s | -7.74 | -0.01 | 3.1% |
| book - T_p, game-ending points | 74 | -1.53 s | -4.21 | +0.08 | 5.4% |
| book - T_p, moves >= 3c | 246 | -1.30 s | -2.93 | +0.07 | 2.0% |
| ESPN game - T_p (game-ending point) | 40 | +27.46 s | +20.1 | +30.0 | - |
| PM sports game - T_p | 62 | +29.10 s | +16.7 | +41.8 | - |
| WTA API point - T_p | 159 | +43.34 s | +27.4 | +60.6 | - |
| WTA API game - T_p | 41 | +43.11 s | +25.8 | +64.0 | - |
| WTA point-by-point endpoint - T_p | 255 | +137 s | +104 | +168 | - |

The book reprices before the official stamp in every one of the 9 matches. Per-match medians run from -0.66 s to
-1.93 s. The official stamp has 1-second resolution and may sit 1-3 s after the ball actually lands (umpire
entry), so the book is probably reacting about 0-2 s after the real point end. Either way, a feed built from
the official scoring system cannot beat the book.

**Lead of each source over the book (lead = t_book - t_source; > 0 means the source is first):**

| source (granularity) | n | median lead | p10 | p90 | **share lead > 1.3 s** |
|---|---|---|---|---|---|
| ESPN scoreboard (game) | 40 | -28.2 s | -34.3 | -20.4 | **0.0%** |
| PM sports websocket (game) | 61 | -30.0 s | -42.6 | -17.8 | **0.0%** |
| WTA public API (point) | 153 | -44.1 s | -61.5 | -28.2 | **0.0%** |
| WTA public API (game) | 41 | -44.2 s | -62.9 | -26.3 | **0.0%** |

### 3b. Source clock, all matches (M2: biggest implied move in [-90 s, +30 s])

| source | n | median lead | p10 | p90 | share > 1.3 s |
|---|---|---|---|---|---|
| ESPN (all) / ATP / WTA | 67 / 27 / 40 | -58.0 / -66.8 / -54.1 s | -85.3 | -5.5 | 9.0% / 18.5% / 2.5% |
| PM sports (all) / ATP+Chall. / WTA | 142 / 79 / 63 | -59.4 / -64.0 / -54.1 s | -83.9 | -16.8 | 5.6% / 7.6% / 3.2% |
| WTA API point | 152 | -38.5 s | -76.3 | +13.0 | 14.5% |

M2 agrees on the sign and on ATP vs WTA. Its magnitudes are biased early, and its small "> 1.3 s" shares are
artefacts of the window: they vanish on the official clock, where the same WTA units show 0/194 leading. For ATP,
the PM sports and ESPN distributions match their WTA ones, which is consistent with the same ~28-30 s
architecture lag.

### 3c. Source vs source on the same game (no book needed)

* ESPN vs PM sports (n = 64): ESPN is first 37.5% of the time, with a median 1.9 s lead once stalls are excluded.
  **But ESPN stalled for 2-30 minutes on 15.6% of games.** Two ATP Beijing matches (Zverev-Shang, Cerundolo-Mensik)
  froze for 10-30 min. PM sports never stalled by more than 120 s in that pairing.
* ESPN is 15.0 s ahead of the WTA API (first 81% of the time). PM sports is 13.6 s ahead of the WTA API (first 74%).

### 3d. Why each source is slow (out/summary.json -> cadence)

* PM sports websocket: messages per game arrive with a median gap of 32.8 s (p90 86 s), as batched snapshots
  rather than per-point pushes. This matches the ~55 s median lag measured earlier for this feed.
* ESPN: `cache-control: max-age=1`, 30 ms responses, so the poll is not the bottleneck. ESPN's upstream is
  about 27 s behind the umpire, and it can stall.
* WTA API: CloudFront `max-age=30`. 95% of polls are cache hits with a median age of 15 s, so a perfect 2 s poll
  still sees data that is 15 s stale on average, on top of a backend that is already 20-30 s behind. The
  point-by-point log is 2+ minutes behind.
* Even a cache-free WTA feed would be bounded by its own timestamp, which the book already beats by 1.2 s.

**Answer: none of the public sources beats the book.** In this sample, 0 of 295 matched observations led by
more than 1.3 s. The Polymarket moneyline is the earliest public signal of who won the point. It picks the
correct winner in 96% of points and arrives about 28 s before ESPN.

## 4. (i) Does the moneyline reprice before the side markets? (live, 1.56 h, 14 matches, 642 ML jumps)

Anchor: every moneyline jump of at least 1c within 2 s, at least 10 s apart. For each side market that is still
alive (mid between 3c and 97c, quoted before the jump), find the half-move reprice in [-5 s, +30 s].

| side market | pairs | share that moved | median lag | p25 / p75 | share of movers lagging > 1.3 s | live median spread |
|---|---|---|---|---|---|---|
| set_winner | 388 | 35.3% | 2.7 s | 0.2 / 16.6 | 59% | 11.5c |
| first_set_winner | 358 | 37.7% | 3.0 s | 0.2 / 9.8 | 61% | 8c |
| match_totals | 1726 | 29.0% | 6.1 s | 1.3 / 18.0 | 74% | 13c |
| set_handicap | 388 | 11.6% | 4.1 s | 0.4 / 11.8 | 69% | 13c |
| game_handicap | 357 | 11.8% | 1.8 s | 0.9 / 12.7 | 55% | 29.5c |
| set_totals | 404 | 0.5% | - | - | - | 18.5c |
| first_set_totals | 563 | 0% | - | - | - | 44c |
| all | 4184 | 20.6% | 4.4 s | 1.0 / 16.3 | 68% | ML: 1c |
| cut: ML jump >= 3c | 326 | 29.8% | 1.3 s | 0.5 / 3.3 | 49% | |
| cut: ML jump at an official WTA point | 1444 | 20.2% | 2.1 s | 0.9 / 7.1 | 65% | |

Yes, the moneyline leads: the side markets reprice later, often seconds later. They are also thin (spreads of
8-44c against 1c on the moneyline; 6-5,000 quote updates per market against ~150,000 on the moneyline). But
their makers **pull** quotes instead of leaving them stale. At t_ML + 1.3 s, only **12.3%** of the 587 lagging
side markets still had any depth at prices better than their post-reprice mid. Sweeping all of it:

* would have netted **+$607 in total (+$388/h)** if valued at the new mid and held, with a 5% fee;
* would have netted **-$3,246 (-$2,077/h)** if exited at the post-reprice opposite touch, with two fees;
* would have netted -$28 (hold) / -$300 (exit) on large ML jumps (>= 3c) only, and -$12 / -$342 on jumps at
  official WTA points only.

The only market type with a positive hold value is set_winner (+$378 over 81 lagging events). That number comes
from looking at 7 market types after the fact, it is negative on exit, and it covers 1.5 h. It is a hypothesis
for forward testing, not an edge.

## 5. (ii) Depth at stale prices: what could have been taken

Because no public source leads the book, the window in which a public-feed trader could hit stale quotes is
empty. 0 of 295 observations led by more than 1.3 s, so there is nothing to measure at t_source + 1.3 s. The
upper bound is an **oracle** that knows the point outcome before the book. Below is the depth resting on the
moneyline at prices better than the mid 3 s after the reprice (482 points; `out/stale_depth.csv`):

| snapshot (relative to book reprice) | median $ resting | mean $ | mean net edge, hold @ new mid (5% fee) | mean net, exit @ new touch (2 fees) |
|---|---|---|---|---|
| t_book - 2 s | $565 | $3,116 | +$20.9 / point | -$71 |
| t_book - 1 s | $379 | $1,866 | +$18.2 / point | -$38 |
| t_book - 0.25 s | $222 | $1,254 | +$17.6 / point (median -$0.11) | -$21 |
| t_book + 0.5 s | $0 | $113 | -$0.8 | -$4 |

The stale depth is gone 0.5 s after the reprice. Because of the 1 s order delay, an order has to be sent at
least 1.3 s before the reprice to meet it, which means at least 2.5 s before the official stamp. Even with that
foresight, the edge is a +$18/point mean (median about $0). It only pays on big jumps (moves >= 3c: +$38/point
at -0.25 s), and only if held to resolution. Exiting at the touch loses after two fees.

**Prints around the reprice** (`out/trades_around_reprice.csv`): $101k of moneyline volume printed in the
0.5 s after the reprice, 96% of it in the direction of the move, at -0.33c/share net against the +3 s mid.
Prints landing 0-0.5 s *before* the reprice were 98% with the move and earned +0.91c/share net. Those orders were
submitted at least 1 s before they printed. So the takers who move the book have the point outcome at least
1-1.5 s before the reprice. That is consistent with the courtside or low-latency-video **fast tier** found in
the in-sample work, and it is not reachable from any public feed.

## 6. What this means for the strategy

* A remote, public-data latency strategy is **not executable**. Every public feed lags the book by 17-62 s
  (p10-p90). The venue's 1 s delay plus about 0.3 s of network leaves no margin, and the fast tier operates
  inside a window that would need foresight of about 2.5 s before the official stamp.
* The only remote-executable timing signal is **the moneyline book itself**. Cross-market lag is real
  (side markets reprice a median of 2-6 s later when they move), but side-market makers pull rather than leave
  stale size. On the live day, the conservative (exit) P&L of sweeping what remained was negative. The set-winner
  hold-value result is the one lead worth a forward test (pre-registered: ML jump >= 1c, sweep set_winner levels
  better than the post-reprice mid at t+1.3 s, hold).
* The Polymarket sports feed must not be used as a clock for "jump onset": it is 29 s behind the umpire.

## 7. Variants (16 measurement configurations, none tuned)

3 sources (PM sports, ESPN, WTA API) × 3 book-matching definitions (M1 half-move, M1 first-tick, M2 biggest move)
= 9. Then: the WTA point-by-point endpoint delay; cross-market at ML jump >= 1c, plus 2 pre-declared cuts
(>= 3c, at an official point); cross-market stale depth; moneyline stale depth at 4 snapshots; prints around the
reprice. That makes 16 (listed in `results.json -> variants`). There are no free parameters chosen on outcomes.
The windows (90/30 s from the task; 10/25 s around official points), the 1c jump threshold and the 5c/10c spread
filters were fixed before results were seen, except for one change: the M1 forward window was trimmed by 4 s
after an inspected outlier showed it captured the next point. The previous run (n = 454, before the trim) gave a
median of -1.15 s and a share > 1.3 s of 5.7%. The final run (n = 482, after the trim) gives -1.16 s and 3.7%. In-sample walk-forward by month and by regime does not apply:
this lens has no trading rule, and the data is live 2026-10-03 data in the 1 s / 5% regime only.

## 8. Caveats

* **One day, one tournament for the official clock.** M1 covers 9 WTA matches, mostly at Beijing WTA 1000 plus
  one WTA 125. ATP and Challenger have no public point-level official clock (the ATP sites are bot-protected), so
  for them only the M2 and source-vs-source results apply. Asian evening sessions and European indoor events may
  differ.
* The official WTA timestamp has 1-s resolution, and its offset from the actual ball landing is unknown.
* The ML jump detector (1c / 2 s) also catches quote flicker, which deflates "share moved" in the cross-market
  table. The >= 3c and official-point cuts are the cleaner views.
* Stale-depth valuation at the new mid assumes it is fair. A side-market mid inside a 10-30c spread is a noisy
  value; the exit valuation is the conservative bound.
* Recorder gaps: a DNS blip at 11:13 UTC left both sports websockets alive but silent. Mine reconnected at 11:23
  after a restart that added an idle watchdog. The `src/live_recorder.py` sports socket (PID 43753) has been
  **silent since 11:13 UTC and is still running**. Its market socket is fine. I did not touch it, per
  instructions. Other lenses that read `data/live/sports_*` after 11:13 should know this. Changes first seen
  after an outage were dropped (3 units).
* Official point logs for matches that ended before 11:08 come from a one-off cached fetch (`fetch_pbp.py`).
  They are official score data, not market data, and are used only as a clock against books that were recorded
  live.

## Recorders (still running)

* `research/v2/latency/recorder.py`: **PID 73582**, started 2026-10-03 11:23 UTC with `--hours 20` (self-stops
  about 07:23 UTC on 2026-10-04). Writes `data/live_v2/*.jsonl`, gzipped hourly. Log: `data/live_v2/recorder.log`.
  Stop with `kill 73582` (or `pkill -f research/v2/latency/recorder.py`). The first run, PID 69011
  (11:08-11:23 UTC), was stopped to add the idle-reconnect watchdog. Its files are kept and read.
* `src/live_recorder.py` (PID 43753): not started or stopped by this lens. Its sports socket is silent since
  11:13 UTC (see caveats).

Re-run `fetch_pbp.py` and `analyze.py` at any time to fold in the newer recording. The numbers in this file
are from the analysis run at 12:45 UTC on 2026-10-03, which is the snapshot in `out/` and `results.json`.
Because the recorder keeps running, a re-run will add data and move the numbers slightly.
