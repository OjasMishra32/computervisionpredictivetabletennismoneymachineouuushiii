# TT5: how fast the edge after a score event decays, and what each latency stack can still earn

Pre-registered in `HYPOTHESIS_TT.md` (TT5). Pre-run decisions in `research/decay/PRERUN.md` (TT5-D1 to
TT5-D3); the same three entries were committed in `research/tt/DEVIATIONS.md` by `eb0e692` at 19:23 UTC,
before this run started at 19:25:45 UTC. The run is logged in `results/tt/peeks.log` and
`results/oos_peeks.log`.

Every number below comes from `scripts/signal_decay.py`. Outputs: `results/decay/decay.json` (all
statistics), `results/decay/tables.md` (every table, every subset), `results/decay/stamp_gaps.json`
(tape time resolution), `results/decay/fig_signal_decay.png`. The run took 766 s on the laptop, in one
process with a 5.4 GB peak. **HiPerGator was not used.**

Units: ¢ per share. "net30" is the taker's 30 s markout minus the taker fee, rate·p(1−p). CIs are 95%,
match-clustered (`fasttier.cluster_ci`, 2,000 draws, seed 0). The x-axis is `since_det`, the seconds from
the latest jump detection to the print, on the tape's block clock.

## Bottom line

1. **Tennis: only the fast tier earns, at any delay.** After the fee, the average taker who trades in the
   jump's direction loses at every delay: −0.35 in the detection block, −0.70 at 1–3 s, and −0.65 to −0.72
   from 3 s to 30 s. The walk-forward fast tier earns +1.09 in the detection block and +0.53 at 1–3 s.
2. **The edge decays within about 3 s in today's regime** (burned OOS: Aug–Oct 2026, 1 s order delay,
   5% fee). Before fees, with-jump takers make +0.65 in the detection block, +0.66 at 1 s and +0.51 at
   2 s. By 3–5 s that is down to +0.12, and by 10–30 s to +0.03. The fee is 0.95–0.99 here, larger than
   the gross edge at every delay. The pre-registered decay test passes in this period
   (+0.66 [+0.45, +0.87]) but not pooled over the year (+0.19 [−0.26, +0.46]).
3. **The tape cannot tell the CV stacks apart.**
   - Camera + CV + network + the 1 s venue delay puts an order at x = 1.03–1.16 s. Florida vs London and
     a 20 ms vs 50 ms vs measured 84 ms model all fall in the same bin.
   - **Tennis Reading A** (each market's own delay): with-jump −0.44 [−0.55, −0.31]; fast tier
     +0.65 [+0.53, +0.76] (+0.53 at block resolution).
   - **Today's regime:** with-jump −0.29 [−0.49, −0.08] in [1, 2), fast tier +0.41 [+0.07, +0.77].
   - **Upper bound** (Reading B, detection block): with-jump −0.35, fast tier +1.09.
4. **Slow stacks are back at baseline.**
   - A public stream viewer (6.3–31.3 s) reads −0.72 to −0.62.
   - The public score feed (45.6 s, h4) reads −0.62, the no-jump baseline.
5. **Table tennis cannot answer TT5.**
   - The data: 27 matches, 1,002 prints and 90 detections. No fast-tier wallet qualifies in any month.
   - The pre-registered decay test is **not computable**: [1, 2) holds 0 with-jump prints.
   - Its CIs are up to 25¢ wide. The CV stack reads off a **single print** (−6.94).
   - Reading B is −1.67 [−6.04, +2.62] (75 prints, 27 matches). Nothing here is evidence either way.

### Why the live result cannot look like the backtest
The v2 backtest fills at the fast tier's own prices in the 0–3 s after detection. Most of those prints
are in the detection block itself: 104,343 of the 128,000 fast-tier prints in 0–3 s that have a 30 s
markout. That is Reading B: +1.09 pooled and +0.75 in today's regime. A live taker cannot be there:
- The venue holds every order for 1 s (Reading A).
- The public data-api tape shows the detection print about 2 s after it trades. A bot that detects jumps
  from that tape cannot act before x ≈ 2 + 1 s, which is the [3, 5) bin. There, with-jump takers make
  −0.65 pooled and −0.85 in today's regime, and even the fast tier's own prints make −0.66 in today's
  regime.

At our best stack the curve gives an average with-jump taker −0.29 to −0.44 per share. The fast tier is
still positive there, but it knows the point; following the tape does not. The CLOB websocket (millisecond
stamps) removes the 2 s tape delay but not the 1 s venue hold.

## 1. Data

| | tennis (U1 IS + burned OOS, non-blind) | table tennis (UTT, first look) |
|---|---|---|
| matches / taker prints | 11,926 / 9,556,554 | 27 / 1,002 |
| detections (J = 4¢, 10 s / 60 s) | 268,345 | 90 |
| delays (matches) | 1 s: 7,065 · 3 s: 4,861 | 1 s: 19 (Setka) · 3 s: 8 (WTT) |
| fast tier (walk-forward, H6/TT2 rule) | 4 wallets (2025-12) → 117 (2026-10) | 0 wallets in every evaluated month (2026-04, -05, -07, -09) |
| subsets also reported | IS (9,581), burned OOS (2,345; all 1 s / 5%) | WTT (8), Setka (19), IS (24), OOS (3), UTT + 96 unlisted markets (34) |

## 2. Time resolution and the block-time stamp

- **What the stamps are.** data-api timestamps are Polygon block times in whole seconds. Matched by
  transaction hash, they lag the CLOB match time by a median 1.98 s (p10 1.95, p90 2.97, n = 5,472;
  `research/v2/blocklag`).
- **Block cadence** (`results/decay/stamp_gaps.json`; shares of the 1–6 s gaps between consecutive prints
  in a match):

  | tape | quarter | 1 s | 2 s | 3 s | 4 s |
  |---|---|---|---|---|---|
  | tennis IS | 2025-Q4 | 0.000 | 0.507 | 0.000 | 0.290 |
  | tennis IS | 2026-Q1 | 0.000 | 0.535 | 0.000 | 0.292 |
  | tennis IS | 2026-Q2 | 0.100 | 0.462 | 0.102 | 0.182 |
  | tennis IS | 2026-Q3 | 0.270 | 0.257 | 0.227 | 0.069 |
  | tennis burned OOS | 2026-Q3 | 0.250 | 0.243 | 0.241 | 0.076 |
  | table tennis | 2026-Q1 / Q2 / Q3 | 0 / 0 / 0.194 | | | |

  Until 2026-Q1 the stamps step in 2 s, so `since_det` is even. 1 s gaps appear in 2026-Q2 and make up a
  quarter of short gaps by Q3.
- **Effect on the bins.**
  - The pre-registered [1, 2) bin holds only prints from 2026-Q2 on: 29,872 with-jump tennis prints, but
    0 in table tennis.
  - The code check behind TT5-D3 used Oct–Nov 2025 matches and found [1, 2) empty. That is true for the
    2 s era only, so the pre-registered test turned out computable for tennis and stays the primary. The
    block-resolution version ([1, 2) and [2, 3) merged into [1, 3)) is reported alongside it.
  - [0.25, 0.5) and [0.5, 1) are empty by construction.
- **How the axis shifts.**
  - `since_det` is the difference of two block stamps, so the ~2 s lag cancels. What is left is up to
    about 1 s of jitter (p10–p90 of the lag) plus block quantisation (2 s, later ~1 s).
  - The "same block" bin (0 s) can hold prints that traded just *before* the detection print.
  - In real time, a bot reading the data-api tape learns of a detection about 2 s late. Its earliest
    reachable bin is therefore [3, 5) at a 1 s venue delay, not [1, 2).
  - The detection itself lags the move's onset by up to the 10 s short window. On live WTA points, the
    book reprices a median 1.16 s before the official point stamp (`research/v2/latency`).

## 3. The curves (net30, ¢/share)

**Tennis, all periods pooled (pre-registered bins; [0.25, 0.5) and [0.5, 1) empty):**

| since_det | all takers | with-jump | against-jump | fast tier | others | n with-jump / matches |
|---|---|---|---|---|---|---|
| 0 (same block) | −0.45 [−0.57, −0.27] | −0.35 [−0.44, −0.28] | −0.75 [−1.13, −0.06] | +1.09 [+1.06, +1.13] | −0.94 [−1.10, −0.70] | 331,784 / 11,837 |
| [1, 2) | −0.81 [−1.09, −0.63] | −0.49 [−0.94, −0.24] | −1.40 [−1.55, −1.26] | +0.54 [+0.40, +0.68] | −1.17 [−1.52, −0.95] | 29,872 / 5,414 |
| [2, 3) | −1.00 [−1.21, −0.82] | −0.79 [−1.15, −0.52] | −1.31 [−1.50, −1.14] | +0.52 [+0.39, +0.65] | −1.26 [−1.51, −1.04] | 62,167 / 8,708 |
| [3, 5) | −0.95 [−1.06, −0.85] | −0.65 [−0.75, −0.56] | −1.31 [−1.54, −1.13] | +0.27 [+0.14, +0.40] | −1.13 [−1.26, −1.03] | 83,079 / 9,403 |
| [5, 10) | −0.86 [−0.92, −0.81] | −0.72 [−0.82, −0.61] | −1.03 [−1.11, −0.95] | +0.51 [+0.39, +0.63] | −1.05 [−1.12, −0.99] | 139,151 / 9,958 |
| [10, 30) | −0.84 [−0.88, −0.81] | −0.68 [−0.73, −0.64] | −1.03 [−1.11, −0.96] | +0.79 [+0.74, +0.84] | −1.12 [−1.16, −1.07] | 529,611 / 11,117 |
| baseline | −0.65 [−0.66, −0.65] | −0.62 [−0.64, −0.61] | −0.68 [−0.69, −0.66] | +0.62 [+0.60, +0.63] | −0.89 [−0.90, −0.88] | 3,547,863 / 11,915 |

**Tennis, today's regime (burned OOS, 2,345 matches, all 1 s / 5%), with the fee added back:**

| since_det | with-jump net30 | mean fee | with-jump gross | fast net30 | fast gross |
|---|---|---|---|---|---|
| 0 | −0.34 [−0.41, −0.27] | 0.99 | +0.65 | +0.75 [+0.66, +0.85] | +1.73 |
| [1, 2) | −0.29 [−0.49, −0.08] | 0.95 | +0.66 | +0.41 [+0.07, +0.77] | +1.37 |
| [2, 3) | −0.46 [−0.67, −0.26] | 0.97 | +0.51 | −0.02 [−0.29, +0.27] | +0.94 |
| [3, 5) | −0.85 [−1.01, −0.70] | 0.98 | +0.12 | −0.66 [−1.14, −0.30] | +0.32 |
| [5, 10) | −0.75 [−0.93, −0.57] | 0.99 | +0.24 | −0.05 [−0.29, +0.16] | +0.94 |
| [10, 30) | −0.95 [−1.06, −0.85] | 0.98 | +0.03 | +0.42 [+0.24, +0.59] | +1.41 |
| baseline | −0.76 [−0.79, −0.72] | 0.85 | +0.10 | +0.37 [+0.33, +0.40] | +1.25 |

The fast tier is positive in the baseline too (+0.62 pooled, +0.37 OOS). Its wallets are better than
other takers in general, so not all of their edge is post-jump latency. Their excess over their own
baseline is largest in the detection block.

**Table tennis (UTT, block-resolution bins; fast tier empty):**

| since_det | all takers | with-jump | n with-jump / matches |
|---|---|---|---|
| 0 | −0.83 [−4.60, +2.39] | −1.67 [−6.04, +2.62] | 75 / 27 |
| [1, 3) | −3.11 [−11.01, +3.52] | −6.94 (one print) | 1 / 1 |
| [3, 5) | −1.18 [−3.09, +3.55] | −0.40 [−2.46, +3.99] | 6 / 4 |
| [5, 10) | −0.76 [−8.83, +8.57] | +4.01 [−6.13, +18.33] | 15 / 8 |
| [10, 30) | −1.79 [−5.64, +2.18] | −1.56 [−7.24, +3.48] | 46 / 19 |
| baseline | −1.48 [−3.17, +0.11] | −2.99 [−6.33, −0.85] | 273 / 26 |

The league, IS/OOS and sensitivity subsets (`tables.md`) are just as noisy. Adding the 96 unlisted
markets (34 matches) changes no conclusion. Net-to-resolution figures for table tennis run to ±25¢. They
are dominated by post-match prints (no table tennis market has a finish time) and by a handful of match
outcomes, so they are not interpreted.

**Net to resolution (secondary), tennis pooled, with-jump:** +0.12 at [1, 2) and −0.76 at [10, 30). Its
paired decay is +0.88 [+0.05, +1.71], positive, but held-to-resolution markouts are far noisier per match.

## 4. Decay test (with-jump net30, early bin minus [10, 30), paired match bootstrap)

| sport · period | pre-registered: [1, 2) − [10, 30) | block resolution: [1, 3) − [10, 30) |
|---|---|---|
| **tennis, IS + burned OOS (primary)** | **+0.19 [−0.26, +0.46]: no decay shown** (29,872 vs 529,611 prints) | −0.02 [−0.29, +0.21]: no decay shown |
| tennis, IS | +0.09 [−0.47, +0.43]: no decay shown | −0.11 [−0.43, +0.15] |
| tennis, burned OOS (1 s / 5%) | **+0.66 [+0.45, +0.87]: decays** | +0.58 [+0.42, +0.73]: decays |
| **table tennis, UTT (primary)** | **not computable** (0 with-jump prints in [1, 2)) | −5.38 [−10.48, +0.17] from **one** print; 734 of 2,000 draws undefined; not interpretable |

In tennis the with-jump net30 is roughly flat from 1 s to 30 s (−0.5 to −0.8). It sits below both the
same-block value (−0.35) and the baseline (−0.62), so the pooled pre-registered test finds no decay. In
today's regime the gross edge falls from +0.66 at [1, 2) to +0.03 at [10, 30), and the test passes.

## 5. Latency stacks mapped to the curve

Pre-venue latency ℓ = camera 8.3 ms (one frame at 120 fps) + CV + network. Reading A uses x = ℓ + δ, the
bin of each market's own venue delay δ (1 s → [1, 2) pre-registered or [1, 3) block; 3 s → [3, 5)).
Reading B uses x = ℓ, an upper bound because the venue delay cancels on the tape clock.

| stack | ℓ | x (δ = 1 s) | tennis with-jump, A | tennis fast tier, A | tennis OOS with-jump, A | TT with-jump, A |
|---|---|---|---|---|---|---|
| (c) FL-20: CV 20 ms + Florida 67 ms | 95.3 ms | 1.095 s | −0.44 [−0.55, −0.31] | +0.65 [+0.53, +0.76] | −0.29 [−0.49, −0.08] | not computable (0 prints) |
| (c) FL-50 | 125.3 ms | 1.125 s | same bin, same value | | | |
| (c) FL-meas: measured CV 84.3 ms | 159.7 ms | 1.160 s | same bin, same value | | | |
| (d) LDN-20: CV 20 ms + London 2 ms | 30.3 ms | 1.030 s | same bin, same value | | | |
| (d) LDN-50 | 60.3 ms | 1.060 s | same bin, same value | | | |
| (d) LDN-meas | 94.7 ms | 1.095 s | same bin, same value | | | |
| CV stacks, Reading B (x = ℓ, same block) | | 0.03–0.16 s | −0.35 [−0.44, −0.28] | +1.09 [+1.06, +1.13] | −0.34 [−0.41, −0.27] | −1.67 [−6.04, +2.62] |
| CV stacks, block resolution A | | | −0.44 [−0.53, −0.34] | +0.53 [+0.43, +0.63] | −0.37 [−0.52, −0.22] | −6.94 (1 print) |
| (a) stream viewer, 5 s delay + 0.25 s reaction + 67 ms | 5.32 s | 6.3 s → [5, 10) | −0.72 [−0.82, −0.61] | +0.51 | −0.75 | +4.01 [−6.13, +18.33] (15 prints) |
| (a) stream viewer, 30 s delay | 30.32 s | 31.3 s → baseline | −0.62 [−0.64, −0.61] | +0.64 | −0.76 | −2.99 [−6.33, −0.85] |
| (b) fastest public feed (ESPN, 28.2 s behind the book) | 28.27 s | 29.3 s → [10, 30); 3 s markets → baseline | −0.58 [−0.60, −0.56] | +0.82 | −0.95 | −3.28 [−8.88, +0.13] |
| (b) public score feed (h4: book leads by 44.5 s) | 44.59 s | 45.6 s → baseline | −0.62 [−0.64, −0.61] | +0.64 | −0.76 | −2.99 [−6.33, −0.85] |

- **The tape cannot separate London from Florida** (a 65 ms difference), or the 20 ms, 50 ms and measured
  84 ms models. At whole-second stamps they share one bin. That does not make the difference zero; it is
  unmeasured. Measuring it needs millisecond book data for these markets.
- **Measured CV latency.** `results/engine/vision_bench.json` gives a bounded call latency of p50
  84.3 ms and p90 127.2 ms. That is on the M4 laptop, which drops frames to bound lag: it cannot keep up
  with 120 fps unbounded, and the classifier is a stand-in with calls disabled. A GPU number was not
  measured. The H3 call lead (median 25 ms before the reference frame) is not credited, as
  pre-registered.
- **Every latency input is measured on tennis.** The stream delay (5–30 s) is an assumption. The public
  feed lags (h4: n = 75, 93% book-first; ESPN from `research/v2/latency`) were measured on tennis, and
  nobody has measured table tennis feeds.
- **Assumption, as pre-registered:** the physical point happens at the detection time.

## 6. Caveats

- **Tennis is non-blind.** These prints have been studied before (v2 and others).
- **Table tennis is a first look** but tiny: 27 matches, and 3 OOS matches. No CI there supports a claim.
- **The fast-tier curves are walk-forward.** Wallets qualify only on earlier months.
- **Prints, not orders.** The curves are markouts of prints that happened. A new order at x would face the
  book that was left at x, which these markouts approximate but do not measure.
- **Not pre-registered.** `net_res`, the fast-tier and other-taker curves, the period splits, the
  stream/feed/measured-CV stacks and the block-resolution bins are secondary (PRERUN.md TT5-D2, TT5-D3).
  None of them changes the pre-registered verdicts:
  - tennis: no decay shown (pooled);
  - table tennis: not computable.

## Reproduce

```
python scripts/signal_decay.py            # full run: decay.json + figure (about 13 min, 5.4 GB peak); logs a peek
python scripts/signal_decay.py --figure   # redraw the figure from decay.json (reads no data)
python scripts/signal_decay.py --tables   # print every table from decay.json (reads no data) -> results/decay/tables.md
python scripts/signal_decay.py --gaps     # tape timestamp gaps only -> results/decay/stamp_gaps.json
```

After the run, the reporting modes (`--figure` layout, `--tables`, `--gaps`) were added and edited in
`scripts/signal_decay.py`. The statistics code is byte-identical to the version that ran.
