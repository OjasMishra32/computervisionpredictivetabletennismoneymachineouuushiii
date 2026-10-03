# Deviations from research/v2/lowloss/PREREG.md

## D1. U2-IS and Combined-IS calendars end on 2026-08-26, not 2026-08-25
Found during the first and only run of `scripts/lowloss_test.py` (2026-10-03 17:36 UTC). No
re-run was needed and nothing was changed in response to a result.

**What happened.** PREREG (b) puts each trade in a period by its match's start, and says the U2-IS
calendar runs from 2026-02-01 to 2026-08-25. Six U2 ITF matches started on 25 Aug before 14:15 UTC
and finished on 26 Aug (Bytom W75, Trieste W35 ×3, Cap d'Agde M15 ×2; the ends are 26 Aug 09:35 to
22:20 UTC, so these were suspended overnight). They have 17 trades, for both policies, entered on
26 Aug. By the period rule they belong to U2-IS. A calendar ending on 25 Aug cannot hold them.

**What was done.** The period rule wins: the trades stay in U2-IS and Combined-IS, and those two
calendars are extended by one day to 2026-08-26. The script does this whenever a trade falls
outside the declared calendar and sets `calendar_extended: true` in `results/lowloss/results.json`.
Dropping the trades instead would have changed the books, not just the day count.

**Effect.** The extra day is a losing day for both policies (v2 −$69.30, v2-safe −$33.79). With
those trades removed, U2-IS would be:
- v2-safe: 69 of 103 active days profitable (67.0%, Wilson 95% lower bound 57.4%), and +2.13¢/share
  with CI [1.40, 2.90].
- v2: 67 of 103 (65.0%, lower bound 55.5%), and +2.05¢/share with CI [1.20, 2.95].

The reported figures with the extra day are 66.3% (lower bound 56.8%) for v2-safe and 64.4% for
v2. P1 and P2 pass in U2-IS either way, so the verdict does not change. The U1 calendars (IS and
burned OOS) did not need an extension.
