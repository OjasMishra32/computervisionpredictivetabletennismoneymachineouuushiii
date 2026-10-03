# Live paper session (B): maker v1 on real Polymarket tennis markets

This is pre-registered in `research/v2/maker/PREREG.md`, section 3. Fills are paper, but the market data is live:
every price, book and trade comes from Polymarket's public, keyless feeds. No order is signed or sent anywhere.

> **Restarted at 20:48 UTC on fixed code.** An audit found three bugs: discovery read only 100 of about 455 open
> tennis events, the taker-control timer priced on a stale book under feed lag, and socket gaps left quotes live
> on an unobserved queue. The first session was stopped at 20:48:00.72 UTC, before it had placed any quote or
> fill. It was restarted with the same command at 20:48:12 UTC. Timed record: `research/v2/maker/DEVIATIONS_LIVE.md`
> L11–L14 and `DEVIATIONS.md` R2.

| | |
|---|---|
| PID | **2001**, run `20261003T204812Z`. `caffeinate -i -w 2001` is PID 2114 and keeps the laptop from idle-sleeping while the session runs |
| Process started | **2026-10-03 20:48:12 UTC** (restart) |
| **Session start** (the `session_start` line, after warm-up) | Written to `results/oos_peeks.log` when the warm-up passes. No universe match starts within the 3 h discovery window until the 02:00 UTC matches enter it at 23:00 UTC |
| Quoting stops | 2026-10-04 11:30:00 UTC |
| Settlement wait | until 2026-10-04 16:00 UTC at the latest, or earlier once every position has resolved. The process then writes `results/live/FINAL` and exits |
| Code | `scripts/live_paper.py` at commit **2c63112**, sha256 `73953c8e8f669af6b5f5bd8aacd6c335274dd639da6c65e664424600562f18ff`. Any change from here on is a deviation |
| First session (stopped) | PID 65274, run `20261003T193534Z`, code 3b522e6 (sha256 `fd695922…`). Session start 19:58:42.795 UTC, stopped by SIGTERM at 20:48:00.72 UTC. 0 quotes, 0 fills and 0 taker orders in every book. Kept: `session_20261003T193534Z.jsonl`, `session_20261003T193534Z_summary.json`, `session_20261003T193534Z.log` (its stdout), `STOPPED_20261003T193534Z` (its exit marker, renamed from `FINAL`), `data/live_maker/raw_20261003T193534Z.jsonl.gz` |
| Books | B1 (primary), B1-rt, B1-full, B1-delay (PREREG 3.6), plus CTRL-taker. CTRL-taker is a taker control and is not pre-registered (`research/v2/maker/DEVIATIONS_LIVE.md` L6) |
| Capital (display only) | $10,000 per book |

Command (from the repo root):

```bash
nohup .venv/bin/python scripts/live_paper.py --no-dashboard --until 2026-10-04T11:30:00Z > results/live/session.log 2>&1 &
```

## Warm-up of the first session (PREREG 3.1). The restarted session repeats it
- **Trade-side check.** 59 of 59 websocket trades agreed with data-api; at least 50 at 95% was needed. The convention
  is that the websocket `side` is the taker side.
- **Timing.** The median data-api lag is 1.96 s (block time). 46 of the 59 fell inside a raw ±2 s window.
- **History.** In-match history was bootstrapped from data-api for the in-play matches: 359 prints.

## Files (restarted session, run 20261003T204812Z)
- `results/live/session.log`: one status line a minute.
- `results/live/session_20261003T204812Z.jsonl`: every event. That covers discovery (now with `gamma_pages` and
  `gamma_events`), state changes, quotes, cancels, fills (with `how`), taker orders and voids, resolutions,
  latency and reconnects. It also covers the new records: feed gaps (`feed_gap`, `feed_gap_end`), per-socket feed
  lag (`lag`, each minute) and lag episodes.
- `results/live/summary.json`: rolling, every 10 s. Mission Control reads its `headline`. The same data is in
  `session_20261003T204812Z_summary.json`.
- `data/live_maker/raw_20261003T204812Z.jsonl.gz` (gitignored): every websocket frame and every other engine input,
  including gap inputs. `--replay` on it re-runs the session item for item (B2: add `--clock server`).

## First session, first 5 minutes (19:58:42 to 20:03:47 UTC)
- **Matches.** No ATP, WTA or Challenger singles match was in play. Columbus (Shelbayh–Krueger) had ended at 19:13
  and Curitiba (Heide–Boscardin Dias) just before the start.
- **Activity.** No quotes, no fills, no taker orders, P&L $0.00 in every book.
- **Feed health.** 25,497 price changes, 176 book snapshots and 69 trades; 0 malformed items, 0 reconnects, latency
  L = 69 ms. 11 markets resolved.
- **What comes next (corrected).** This bullet said 14 matches, a count taken from the truncated first Gamma page
  (L11). With every page read, at about 20:50 UTC Gamma lists 32 universe matches starting between 02:00 and 11:00 UTC
  on 2026-10-04, plus one at 12:30:
  - China Open, including Zverev–Djokovic, Medvedev–Cerundolo and Sabalenka;
  - Japan Open, including Alcaraz;
  - Jingshan, Wuning 3, Bari and Porto 2.

  Tour-level side markets are where in-play side flow exists (VENUE_RULES.md 5b).

## Watching it and after the session
- **Watching.** `tail -f results/live/session.log`, `cat results/live/summary.json`, or the Mission Control page.
- **After 11:30 UTC.** PREREG 3.6–3.7 and 5.5: B2 and B2v replays, B3 (the IS fill model on data-api tapes),
  (C), and `research/v2/maker/LIVE.md`.
