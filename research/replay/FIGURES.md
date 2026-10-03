# Match replay: paper figures and demo video

> **BACKTEST REPLAY on a real match recorded live on 2026-10-03 — assumed 1 s licensed video feed (not
> purchased); bounce time = official point stamp - assumed stamp lag; fills priced against the real recorded
> order book; paper only.**
>
> No match video was received, bought or watched. The figures and the video show the recorded Polymarket order
> book, the official point stamps and the simulated orders. Numbers are from `results/replay/replay.json` and
> `points.csv` (the replay after audit deviation D1, `RESULTS.md`: points whose reference or execution instant
> falls inside a recorder outage are dropped); nothing below changes a result.

| file | made by | what |
|---|---|---|
| `results/replay/fig_replay_points.{png,pdf}` | `scripts/match_replay_figs.py` | the race on four points, V = 0 / 0.5 / 1 s (6.5 in wide, 11 pt, 300 dpi PNG + vector PDF) |
| `results/replay/fig_replay_pnl.{png,pdf}` | `scripts/match_replay_figs.py` | cumulative P&L over the 9 matches and net per share with CIs |
| `results/replay/replay_match.mp4` | `scripts/match_replay_video.py` | 1920x1080, 30 fps, 44.4 s demo of the selected match |
| `results/replay/selected_match_tob_events.csv.gz`, `selected_match_trades.csv`, `seed_fills.csv` | `scripts/match_replay_extras.py` | event-level book and prints of the selected match; fills of seeds 0-19. The script checks that seed 0 reproduces `points.csv` fill by fill, that every seed reproduces `seed_robustness.csv`, and that the event book matches the 250 ms grid and every `ask_at_exec` |

The paper figures use Source Sans 3 from `docs/paper/fonts/` when it is present (this build), otherwise
Helvetica Neue. Every text span in the PDFs is 11 pt.

## Captions (for the paper)

**Figure A. At a 1 s feed our order reaches the book after it has repriced. Only a faster feed wins the race,
and only on some points.** Four points of Xinran Sun v Cristina Bucsa (WTA Beijing), recorded live on
2026-10-03. Top of each panel: the called player's best ask in the recorded Polymarket book (every change), our
limit (the ask at the assumed landing + 1c), the book's half-move reprice (dashed) and the umpire stamp
(dotted). Landing = stamp − 2.0 s, which is assumed. Grey dots are recorded trades. Bottom of each panel: for
V = 0, 0.5 and 1 s, the assumed feed delay plus 20 ms of inference (light), then 67 ms of network plus the
venue's 1 s taker delay (dark). Each bar ends where the order executes: a dot if it filled, a cross if it
missed because the ask had moved past the limit. Panels are picked by display rules. (a) The V = 1 s order
whose execution minus reprice is closest to the match median (+1.67 s). (b) The largest matched book move with
an order at all three V (9.5c). (c) The largest move where the V = 0 order filled before the reprice. This one
is picked on the outcome and is not representative. (d) The first simulated wrong call that filled at V = 1 s.
It has no matched reprice. BACKTEST REPLAY on a real match recorded live on 2026-10-03 — assumed 1 s licensed
video feed (not purchased); bounce time = official point stamp - assumed stamp lag; fills priced against the
real recorded order book; paper only. Source: `results/replay/points.csv`,
`selected_match_tob_events.csv.gz`, `selected_match_trades.csv`.

**Figure B. The replayed trader loses money at every feed delay, and loses the most at the 1 s headline.**
(a) Cumulative P&L over the 9 matches, marked at the +30 s mid and plotted by execution time. Lines are seed
0; bands are the range over 20 seeds (V = 0 and 1 s). End values: −$179 (V = 0), −$170 (0.5 s), −$224 (1 s).
(b) Net cents per share with a match-clustered 95 % CI (10,000 resamples), marked (filled) and held to the
match result (open). Marked: −0.61 [−0.90, −0.38], −0.66 [−0.96, −0.41], −0.94 [−1.28, −0.58]. Stamp lag
2.0 s, model lead, Florida 67 ms. BACKTEST REPLAY on a real match recorded live on 2026-10-03 — assumed 1 s
licensed video feed (not purchased); bounce time = official point stamp - assumed stamp lag; fills priced
against the real recorded order book; paper only. Source: `results/replay/points.csv`, `seed_fills.csv`,
`replay.json`.

**Caveat for both captions (audit, `RESULTS.md` §7 and §9).** The figures draw the venue's 1 s delay as continuous, as the protocol does. The recorded prints cluster in the first 100 ms of each server second, so delayed orders probably match in whole-second batches; under that reading the replay loses more, not less. Points inside a recorder outage are not drawn as orders (deviation D1).

## Demo video (`replay_match.mp4`)

The persistent ribbon reads: "BACKTEST REPLAY · real match recorded live 2026-10-03 · assumed 1 s licensed
feed · fills vs the real order book · paper only". A two-line footer gives the assumptions and the real inputs.

1. **Title (3.4 s).** The match, the question, the assumptions as chips, a line saying no match video was
   received or used, and the full label.
2. **Replay (33 s).** The recorded mid and best bid/ask band scroll past as the match is fast-forwarded (about
   ×360). Each official point is a tick. At V = 1 s every order is marked as a correct-call fill, a simulated
   wrong-call fill or a miss, and calls blocked by the net cap are marked too. The sidebar shows the running
   P&L (marked at +30 s, booked once the mark is known), the counters and the net-position gauge. A race strip
   animates each order: ball lands, CV call, order sent, 1 s venue delay, then fill or miss against the
   recorded reprice. Faint lanes show what a 0.5 s and a 0 s feed would have done. A tape lists the last nine
   orders. Three points play in real time, picked by the rules above: point 3 (the first simulated wrong call
   that filled), point 72 (the typical race) and point 90 (picked on outcome, flagged as not representative on
   screen). At the end: match over, Sun wins 6–4 7–5. At 1 s this match gives −$6 marked and −$2 held, and
   its orders beat the book on 5 of 120 calls.
3. **All 9 matches (8.0 s).** Cumulative P&L at V = 0 / 0.5 / 1 s with 20-seed bands. A stat grid shows calls
   that beat the reprice (30 / 19 / 7 %), net per share with CI, P&L marked and held, and fills. The limitation
   box says the following. No licensed feed was bought. A faster feed lifts the share of calls that beat the
   reprice from 7 % to 30 %, but the trader still loses at every delay, in all 20 seeds and in all 36
   sensitivity cells. The next step is one live session on a licensed low-latency feed.

Not to be said about any of this: that we received Polymarket or match footage (over WebRTC or any other way),
that the replay used live video, or that the trader made money.
