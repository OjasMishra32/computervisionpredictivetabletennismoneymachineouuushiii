# Live paper session (B): maker v1 on real Polymarket tennis markets

This is pre-registered in `research/v2/maker/PREREG.md`, section 3. Fills are paper, but the market data is live:
every price, book and trade comes from Polymarket's public, keyless feeds. No order is signed or sent anywhere.

| | |
|---|---|
| PID | **65274** (`caffeinate -i -w 65274` is PID 65276 and keeps the laptop from idle-sleeping while the session runs) |
| Process started | 2026-10-03 19:35:34 UTC |
| **Session start** (the `session_start` line, after warm-up) | **2026-10-03 19:58:42.795 UTC**. Logged in `results/oos_peeks.log` with commit 114c722 (clean) |
| Quoting stops | 2026-10-04 11:30:00 UTC |
| Settlement wait | until 2026-10-04 16:00 UTC at the latest, or earlier once every position has resolved. The process then writes `results/live/FINAL` and exits |
| Code | `scripts/live_paper.py` at commit 3b522e6, sha256 `fd69592258bb5407d8baac866360293d33256cd2ef78187c882ef3ac393e2408`. The later commit 114c722 recorded at the start does not change this file. Any change from here on is a deviation |
| Books | B1 (primary), B1-rt, B1-full, B1-delay (PREREG 3.6), plus CTRL-taker. CTRL-taker is a taker control and is not pre-registered (`research/v2/maker/DEVIATIONS_LIVE.md` L6) |
| Capital (display only) | $10,000 per book |

Command (from the repo root):

```bash
nohup .venv/bin/python scripts/live_paper.py --no-dashboard --until 2026-10-04T11:30:00Z > results/live/session.log 2>&1 &
```

## Warm-up (PREREG 3.1)
- **Trade-side check.** 59 of 59 websocket trades agreed with data-api; at least 50 at 95% was needed. The convention
  is that the websocket `side` is the taker side.
- **Timing.** The median data-api lag is 1.96 s (block time). 46 of the 59 fell inside a raw ±2 s window.
- **History.** In-match history was bootstrapped from data-api for the in-play matches: 359 prints.

## Files
- `results/live/session.log`: one status line a minute.
- `results/live/session_20261003T193534Z.jsonl`: every event: discovery, state changes, quotes, cancels, fills,
  taker orders, resolutions, latency, reconnects.
- `results/live/summary.json`: rolling, every 10 s. Mission Control reads its `headline`. The same data is in
  `session_20261003T193534Z_summary.json`.
- `data/live_maker/raw_20261003T193534Z.jsonl.gz` (gitignored): every websocket frame and every other engine input.
  `--replay` on it re-runs the session item for item (B2: add `--clock server`).

## First 5 minutes (19:58:42 to 20:03:47 UTC)
- **Matches.** No ATP, WTA or Challenger singles match was in play. Columbus (Shelbayh–Krueger) had ended at 19:13
  and Curitiba (Heide–Boscardin Dias) just before the start.
- **Activity.** No quotes, no fills, no taker orders, P&L $0.00 in every book.
- **Feed health.** 25,497 price changes, 176 book snapshots and 69 trades; 0 malformed items, 0 reconnects, latency
  L = 69 ms. 11 markets resolved.
- **What comes next.** Gamma lists 14 matches in the universe starting between 02:00 and 11:00 UTC on 2026-10-04:
  the China Open, the Japan Open and Jingshan. Tour-level side markets are where in-play side flow exists
  (VENUE_RULES.md 5b).

## Watching it and after the session
- **Watching.** `tail -f results/live/session.log`, `cat results/live/summary.json`, or the Mission Control page.
- **After 11:30 UTC.** PREREG 3.6–3.7 and 5.5: B2 and B2v replays, B3 (the IS fill model on data-api tapes),
  (C), and `research/v2/maker/LIVE.md`.
