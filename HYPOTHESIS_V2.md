# COURTSIDE v2 — frozen rule and forward test, pre-registered

Written 2026-10-03 ~13:10 UTC, before any data for the forward window was fetched or viewed.

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
