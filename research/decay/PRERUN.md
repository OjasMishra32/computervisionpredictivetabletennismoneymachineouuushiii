# TT5 signal decay: pre-run decisions

Written 2026-10-03 19:17 UTC on top of `56a9c8f`, before any TT5 statistic was computed. No markout,
P&L or price figure had been computed on the table tennis prints by this workflow. (This text was first
written into `research/tt/DEVIATIONS.md` at 19:15 UTC; the TT1–TT4 workflow rewrote that file a minute
later, so it lives here, with a pointer appended there.)

## TT5-D1 (deviation, procedure only). TT5 runs on its own script

**What changes.** `HYPOTHESIS_TT.md` says TT1–TT5 run together in `research/tt/tt_test.py`, with outputs
in `results/tt/`. TT5 (signal decay vs latency) is instead run by `scripts/signal_decay.py`, with outputs
in `results/decay/` (`decay.json`, `fig_signal_decay.png`) and a write-up in `research/decay/RESULTS.md`.
The run is appended to `results/tt/peeks.log` with the UTC time and git hash, as pre-registered.
TT-D1 in `research/tt/DEVIATIONS.md` (the TT1–TT4 run) already states that TT5 is its own single run.

**Why.** TT5 was requested as its own deliverable. It uses no TT1–TT4 output.

**What does not change.** The TT5 definition is used as written: prints with `since_det >= 0`;
net30 = mo30 − fee_rate·p(1−p); print-weighted; `fasttier.cluster_ci` (2,000 draws, seed 0); the eight
bins and the baseline row (before the first detection or ≥ 30 s after the latest one); the all,
with-jump and against-jump curves; table tennis (all UTT, and by league) and tennis (U1 IS + burned
OOS) separately; the paired decay test (with-jump [1, 2) minus [10, 30), resampling matches, 2,000
draws, seed 0, "decays" if the CI is above 0); the four stacks (FL-20, FL-50, LDN-20, LDN-50) with
Reading A (x = ℓ + δ_m) and Reading B (x = ℓ). `src/tiers.py` and `src/fasttier.py` are used unchanged.
Prints with no mid 30 s later (`net30` NaN) are dropped before each mean and CI.

## TT5-D2 (additions, not pre-registered). Reported as secondary; never used for the decay verdict
- **Net markout to resolution**, `net_res = mo_res − fee`. Prints in 50-50 matches have no `mo_res` and
  drop out.
- **Fast-tier and other-taker curves.** The fast tier is the H6/TT2 walk-forward rule
  (`fasttier.qualify` on the causal bucket, months[2:] evaluated), on each sport's own prints. A print
  is "fast" if its wallet qualified for that print's month. Only prints in evaluated months are
  labelled fast or other.
- **Period splits.** Tennis IS and burned OOS; table tennis IS and OOS (UTT `oos` flag).
- **More latency stacks**, read with the same rule:
  - public stream viewer: stream delay 5–30 s (an assumption, not measured) + 0.25 s human reaction
    (`research/v2/tier0/PREREG.md`) + 67 ms + δ;
  - public score feed: the book leads the public score by a median 44.5 s (`results/summary.json` h4);
    the fastest public feed measured, ESPN, is 28.2 s behind the book (`research/v2/latency`);
  - CV stack with the **measured** laptop call latency from `results/engine/vision_bench.json`
    (bounded mode p50 84.3 ms, p90 127.2 ms) in place of the assumed 20/50 ms.
- **Table tennis sensitivity** that adds the 96 zero-listed-volume markets that traded
  (`data/tt/prints_unlisted.parquet`), matching TT-D8's choice for TT1–TT3. UTT stays primary.

## TT5-D3 (deviation, added 19:21 UTC; before any table tennis statistic, after a code check on tennis)
**What was seen.** A code check of `scripts/signal_decay.py --dev 400` on the first 400 tennis U1 IS matches
(non-blind data) gave **0 prints in [1, 2)**. Tennis tape stamps step in **2 s**: the gaps between
consecutive prints in a match are 0, 2, 4, 6 … s (first 200,000 IS rows: 38,733 at 0 s, 34,732 at 2 s,
20,003 at 4 s, and no odd gaps in the top ten). That is the Polygon block interval. The parity of the stamps
drifts over months (share of even stamps by month 0.14–0.72), so within one match nearly every `since_det`
is even. The pre-registration assumed 1 s resolution: it marked [0.25, 0.5) and [0.5, 1) empty by
construction but expected [1, 2) to hold `since_det = 1`.

**Consequence.** [1, 2) holds only the rare odd-second gaps (a phase slip in the block clock). The
pre-registered decay test ([1, 2) − [10, 30)) and Reading A for 1 s markets ([1, 2)) are then empty or
nearly empty. A real order sent ℓ + 1 s after the detection trade lands in the detection block or the next
one, depending on the block phase.

**Decision (fixed before the table tennis run).**
- The pre-registered bins, decay test and read-offs are computed and reported exactly as written,
  including "a bin is empty" where that happens.
- Added, labelled *block-resolution*: [1, 2) and [2, 3) are merged into **[1, 3)**, "the next block"
  (`since_det` 1 or 2). The block-resolution decay test is with-jump net30 in [1, 3) minus [10, 30), with the
  same paired bootstrap. Block-resolution Reading A uses [1, 3) for δ = 1 s (x = ℓ + 1 ≈ 1.03–1.16 s) and the
  pre-registered [3, 5) for δ = 3 s, which already spans one block (3 or 4 s).
- The figure draws the block-resolution bins. Both versions are in `results/decay/decay.json`.
- The distribution of `since_det` (counts at 0–10 s) is reported per sport.
