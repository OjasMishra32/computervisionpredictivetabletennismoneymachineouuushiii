# COURTSIDE v2 — frozen rule and forward test, pre-registered

Committed 2026-10-03 13:22 UTC (1f229bc); amended 13:5x UTC (A1 below), before the forward window opens.

## Why a v2, and why a new test
The original OOS (matches from 2026-08-25 14:15 UTC) was opened once for v1 and is now burned: v2's
design used knowledge of how v1 behaved there (big tickets lost money held to resolution). v2 is
therefore tuned on in-sample data only (walk-forward), reported on the burned OOS only as a labelled,
non-blind number, and tested blind on a **forward window**.

Today's live order books between 09:46 and ~12:45 UTC were examined (fill rates, latency, block lag).
Every match starting before 13:00 UTC is excluded from the forward test.

## Frozen v2 rule (from research/v2/sizing `G_50pct_net100`, verified twice, IS only)
1. **Opportunity set:** prints by walk-forward-qualified fast-tier wallets (H6 rule: ≥30 prints in
   the 0–3 s post-jump bucket over ≥10 matches before month m, t > 3 on 30 s markout) inside 0–3 s of
   a jump onset. This is the shadow-book proxy for "being as fast as the fast tier".
2. **Wallet filter at the current fee:** keep a wallet only if its shrunk (n0 = 200) past 30 s
   markout exceeds 0.05·q(1−q).
3. **Price zone:** token price q in [0.05, 0.95].
4. **Risk-parity size:** shares = k · $1,000 / √(q(1−q)), where k sets the training-period mean
   ticket to 50% of the v1 shadow book's; never more than the fast-tier print, never over $1,000.
5. **Per-match net-exposure cap:** |net outcome-0 shares| ≤ 100. Risk-reducing trades are always
   allowed.
6. **Hold to resolution.** No exit orders, so no fill-rate assumptions (live data shows passive exits
   are adversely selected).
7. Fees: each match's own taker fee, `rate·q(1−q)` per share.

## Forward test (evaluated once, by `scripts/forward_test.py`, logged)
- **Window:** ATP/WTA singles moneylines with ≥$5k volume, start ≥ 2026-10-03 13:00 UTC, resolved by
  the time of the run (planned ~2026-10-04 11:30 UTC). Wallet qualification uses all data before
  the window.
- **Primary:** v2-selected trades' 30 s markout net of fee, per share, > 0 with a 95% CI (clustered
  by match) excluding 0.
- **Secondary:** v2 book P&L held to resolution (dollars, per share, hit rate). With ~1 day of matches
  this is expected to be noisy; it is reported, not tested.
- **Also reported:** the H6 claim that the fast tier keeps beating other takers in the window.
- **Fails if** the primary is ≤ 0 or its CI includes 0. Reported either way.

## Amendment A1 — committed 2026-10-03 ~13:57 UTC, before the forward window opens
Two adversarial verifiers (research/v2/verify_v2/) found that the "0–3 s after the jump onset" label
uses hindsight: the onset is the first print of a 10 s window that the detector confirms up to 10 s
later. On the burned OOS, 81% of v2's P&L came from prints before detection. Changes, all made before
the forward run:
1. **Causal window.** The 0–3 s window is measured from jump *detection*
   (`tiers.add_causal_bucket`), and qualification, the wallet filter and the opportunity set are all
   re-derived on it (`v2.run(causal=True)`). The burned OOS is re-reported on this basis:
   +0.60¢/share [0.09, 1.13].
2. **Wallet filter wording.** The threshold is each match's own published fee rate × q(1−q) (0.05
   today; the code always did this).
3. **Capital.** Each position locks capital for 4 h (ex-ante), not until the realised match end.
4. **forward_test.py fixes.** No dedup of prints (identical rows are distinct fills); a dry run drops
   window matches from history instead of truncating; the OOS split is by match start.
5. **Primary metrics.** A dry run on an old two-day window (Sep 10–12, already seen) showed the v2-book
   metric is underpowered for a window under 1 day (+0.65¢, CI −0.10 to 1.34). So:
   - **Primary A (economic claim):** in the causal 0–3 s window, the 30 s net markout of
     walk-forward fast-tier wallets minus that of all other takers. Match-clustered bootstrap. Pass if
     the 95% CI excludes 0.
   - **Primary B (strategy):** the v2 book's share-weighted 30 s net markout > 0, CI excluding 0. With
     <1 day of matches a fail may be underpowered, and it will be reported as such.
   - **Secondary:** v2 resolution P&L, and the same at +½ tick and +1 tick of entry slippage.
6. **Window start moves to 2026-10-03 14:00 UTC.** The original 13:00 start preceded the original
   commit (13:22), and live trade timestamps were read at ~13:03 UTC for the block-lag measurement
   (latency only, no P&L). Starting at 14:00 puts every forward match after this amendment's commit.

## Amendment A2: v2-safe as a secondary forward-test variant (committed 2026-10-03 ~17:31 UTC)
**Timing.** This amendment is committed after the forward window opened at 14:00 UTC.

**What it adds.** One secondary variant, **v2-safe**. It is the frozen v2 with the per-match net
cap lowered from 100 to 50 shares. Everything else is identical.
- It was chosen on in-sample data only. The grid and selection rule were declared before computing
  in `research/v2/lowloss/GRID.md`. The frozen rule and its tests are in
  `research/v2/lowloss/PREREG.md`.
- No forward-window print, trade or P&L was loaded to choose it.

**What it does not change.** v2's primaries A and B, the window and the pass/fail rules are all
unchanged. v2 remains the rule under test.

**How v2-safe is evaluated in the forward window.**
- Same data, same walk-forward and same run as v2, with only the policy swapped.
- Reported per share held to resolution (match-clustered CI), $ P&L, profitable matches and 30 s
  net markout.
- These numbers are **reported, not tested**.

**Blind sub-window.** Matches starting before this amendment were already under way when it was
written. The blind sub-window for v2-safe is therefore matches starting at or after **2026-10-03
18:00 UTC**, reported separately. The full-window figure is labelled as including matches that
started before v2-safe was frozen.

**IS context, honest walk-forward meta-selection, Feb–Aug 2026:**

| | meta-selection | v2 |
|---|---|---|
| profitable calendar days | 79.1% | 79.6% |
| worst day | −$373 | −$551 |
| $ P&L | $25.5k | $40.4k |

v2-safe lowers the cost of a losing day. It does not reduce how often one happens.

## Amendment A3 (2026-10-04T02:18:17Z): forward test not run
The team decided to submit before the pre-registered forward test window closes, so the forward test (scripts/forward_test.py)
and the tier-0 v3 forward secondary (scripts/tier0_v3_forward.py) were NOT run and no forward-window data was read for
them. The paper reports them as "not run (submitted before the forward window closed)". The live paper session was also
stopped (research/v2/maker/DEVIATIONS_LIVE.md L15).

## Amendment A4 (2026-10-04T02:59:14Z): forward test reinstated
Amendment A3 is withdrawn: the team reinstated the forward test before any forward-window data was read for it
(results/forward_peeks.log has no START line; results/v2/forward.json does not exist). The forward test
(scripts/forward_test.py, rules as in A1/A2) and the tier-0 v3 forward secondary (scripts/tier0_v3_forward.py,
research/v2/tier0_v3/PREREG.md) run ONCE at or after 2026-10-04 11:30 UTC, as originally pre-registered, and their results
are reported whatever they are. The live paper session stays stopped (DEVIATIONS_LIVE.md L15).
