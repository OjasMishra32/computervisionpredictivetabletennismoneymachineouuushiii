# COURTSIDE: mock judging against the Systematic Trading rubric

Written Sat 2026-10-03, about 14:30 EDT. I scored the repo the way a quant-firm judge would. I read
`docs/NOTE.pdf` first, as a judge does. Then I skimmed README, `docs/COMPLIANCE.md`, `docs/DEVPOST.md`, the deck
text (12 slides plus speaker notes, read with python-pptx), the HYPOTHESIS/DEVIATIONS trail, `results/`, and
`research/` (rigor, v2/expand, v2/sizing, v2/tier0). The requirement numbers below (R1 to R73) refer to
`research/compliance/REQUIREMENTS.md`.

**Repo state.** Local `main` is at `1ebb458`, one commit ahead of `origin` (`4ba8e88`). There is a lot of
untracked work, and other sessions are still writing. `docs/NOTE.md` and `docs/NOTE.pdf` are the 13:53 build.
`results/oos_peeks.log` had 14 lines at 14:26 and is still growing.

**Live-site check at 14:13 EDT (read-only).** The site serves the same chunks REQUIREMENTS.md cites
(`SystematicTrackPage-tcbiXROm.js`, `shell-Di37dqBY.js`). A token diff against the cached
`gq_systematic.js` finds 4 changed strings, all of them deadline times (10:00 → 11:00 AM). The shell clock reads
`Date.UTC(2026,9,4,15,0,0)`, which is **Sun Oct 4, 11:00 AM EDT**, for both the Devpost submission and the final
code push. The rubric bands, the 11pt/margins rule, the holdout rule and the score cap all match the live text
word for word. The market chips are still EQUITIES, ETFS, FUTURES, FX, OPTIONS and CRYPTO. No prediction
market is named. The "Systematic Trading Track Participant Brief" is still not linked anywhere.

---

## 1. Scorecard

| # | Criterion | Score | Band it sits in (verbatim) | One-line reason |
|---|---|---|---|---|
| 1 | Economic Foundation | **8** | 7–9: "Strong economic rationale with clear articulation of why the strategy should perform. Logical, well-supported arguments." | Clear counterparty and physical persistence; rivals falsified. The traded claim (H6) came after in-sample results, and the note never states the hypothesis in template form. |
| 2 | Innovation | **8** | 7–9: "Strong differentiation from traditional strategies, with unique or novel elements." | Wallet-level latency tiers on on-chain tapes, plus a measured information ladder and a CV lead-time measurement. Not 10: latency arbitrage and courtsiding are known ideas, and the CV results never reach P&L in the note. |
| 3 | Risk Management Plan | **7** | 7–9: "Comprehensive framework with clear plans to mitigate identified risks." | Limits, de-risking rules, kill switches, venue and crowding risk, and a dial tested blind. Missing: the doubled-cost failure, wallet concentration, tail statistics, and which controls were actually backtested. |
| 4 | Liquidity & Capital | **6** | 4–6: "Some consideration of liquidity and capital, but with gaps or oversights." | Excellent live depth and timing measurements. But there is no single capacity figure in dollars, no cost in bps, no doubled-cost line, and the out-of-sample edge is gone at +½ tick, so deployment is not yet "realistic and practical". |
| 5 | Performance & Analytical Evidence | **7** (cap risk: **4**) | 7–9: "Strong use of data and analysis. Well-reasoned performance expectations." | Deep rigor: clustered CIs, walk-forward, slippage stress, blind tests, factor regression, verifiers. The cap can be triggered two ways: fills at the fast tier's own print, and v2 designed after the OOS was opened (§3, C5). |
| | **Total** | **36 / 50** | | **33** if criterion 5 is capped. About **40–41** is reachable with the changes below, within 5 pages. |

**Tie-break: Performance first, then Economic Foundation.** [R55] The cap on criterion 5 is also the tie-break
criterion. Protecting it matters more than any other edit.

---

## 2. Fix before submitting: hard rules a judge or organizer can check

Ordered by how much damage each can do. Each item gives the requirement number, the evidence and the fix.

1. **Font and margins break R3** ("Use 11pt font or larger and standard margins").
   - Measured in `docs/NOTE.pdf`: body Charter 10.0 pt, tables Helvetica 8.3 pt, captions and code 8.5 pt.
   - The margins come from `@page { margin: 0.6in 0.65in }` in `scripts/make_pdf.py`. The text box runs from
     x = 52 to 559 pt and y = 44 to 746 pt.
   - At 11 pt everywhere with 1 in margins, the current text renders to **6.23 pages**. At 11 pt with Word's
     "Moderate" margins (1 in top and bottom, 0.75 in sides) and line-height 1.3, it renders to **5.61 pages**.
   - I measured both by rendering copies in my scratchpad. The repo was not touched. The page plan is in §4.
2. **Placeholders print in the PDF.** `[FWD_N]`, `[FWD_RES]`, `[FWD_PNL]`, `[FWD_A]` and `[FWD_B]` all appear in
   Table 2.
   - The forward run is planned for about 11:30 UTC (07:30 EDT) Sunday. After it runs, fill the table, rebuild
     the PDF, count the pages and push, all before 11:00 EDT.
   - If the run slips, write "not run by the deadline; pre-registered rule in HYPOTHESIS_V2.md". Never submit
     the raw tokens.
3. **The doubled-cost result is missing from the note** [R31: "show what happens when costs double. If the edge
   disappears, say so."].
   - The result already exists: `results/v2/cost_stress.json`, produced by `scripts/v2_cost_stress.py` from
     `reproduce.sh`.
   - Out of sample, doubling the fee gives **−0.34¢ [−0.86, 0.19], with 0 of 3 months positive**. Doubling the
     fee and adding a half-spread gives −0.84¢ [−1.36, −0.31].
   - In sample, the doubled fee gives +0.77¢ [0.57, 0.98] (7 of 7 months), and doubled costs give +0.27¢
     [0.07, 0.48] (Sharpe 3.0, 5 of 7 months).
   - Out of sample the edge disappears, so the note has to say so. The "costs double" row in `COMPLIANCE.md`
     still points to the slippage stress. Update it.
4. **Annualized return and volatility are missing for both periods** [R7]. Out-of-sample turnover is also
   missing; §7 gives only the in-sample 93× a year.
   - I derived these from `results/rigor/rigor.json` (mean daily % of capital × 365, daily sd × √365) and from
     `results/v2/causal.json`. In sample: **253% / 17.5%**, turnover 93× a year. Burned OOS: **148% / 22.2%**,
     turnover 129× a year.
   - No script prints these numbers yet. Add them to the metrics in `src/v2.py` or to `scripts/rigor_pack.py`,
     and add `rigor_pack.py` to `reproduce.sh`. Today it is not in the script. Any number in the note that the
     code does not print is a risk under R13 and R53.
5. **Not every peek is reported in the note** [R27: "Report every peek in your note."]. The note only says "every
   look is logged". The deck says "3 lines". The log has **14**:
   - v1 once, blind (10:42 UTC);
   - the first runs of 2 pre-registered blind tests on unseen markets (U2 for v2 and for v2-safe);
   - **11 non-blind looks at the burned window**: v2 ×2, v2-safe ×1, cost stress ×1, tier-0 counterfactual ×7.

   Put that breakdown in one sentence in the note (draft in §3, C5).
6. **There is no cost in bps** [R30: "State the cost in bps per trade and justify it."]. My figures, computed from
   `data/v2_trades_is_oos.parquet`:
   - The fee is **≈120 bps of notional in sample**. That period mixes fee rates: 13.5% of trades at 0%, 59.4% at
     3% and 27.2% at 5%.
   - The fee is **≈179 bps out of sample**, where every trade pays 5%.
   - The median spread at entry is 1¢. That makes the half-spread about 99 bps at the average token price of
     about 0.51.
   - The net edge is 2.73¢ per $ in sample and 1.14¢ per $ out of sample (`per_usd_c`), or about 273 and 114 bps.

   Have a script print these figures before you quote them.
7. **Skew and worst month are not shown next to Sharpe** [R35].
   - In sample: skew 0.53, kurtosis 4.3, worst day −1.9%, worst month +$2,543 (no losing month).
   - Out of sample: skew 0.33, kurtosis 3.3, worst day −2.1%, worst month −$434 (October, 3 days).

   `COMPLIANCE.md` claims these are in Table 2. They are not.
8. **Data problems are not discussed** [R32].
   - The universe keeps matches with **lifetime volume ≥ $5k** (`src/tape.py: MIN_VOL`). That volume is only
     known after the match, so the filter is survivorship-like.
   - A missing `fee_rate` is filled with 0. That covers every match from Oct 2025 to Feb 2026 except one in Jan
     and one in Feb, plus 375 of 490 in Mar 2026.
   - The other data handling has no gaps to disclose: binary contracts have no corporate actions, all 13,084
     matches have tapes, and the 2.9% of matches settled 50/50 are included in all P&L.

   Two sentences are enough (draft in §3, C4).
9. **Some sources are not cited** [R16: "Every source you use is cited in the note."].
   - The note uses but does not cite: the Ken French Data Library (factor regression, `data/factors/`), ESPN's
     scoreboard, the WTA public API, Polymarket's sports websocket, and the BlurBall/WASB-SBDT detector weights
     (MIT; DEVIATIONS H3-D6).
   - If the note quotes the rigor pack, also cite Bailey, Borwein, López de Prado & Zhu (2017) and Politis &
     Romano (1994).
   - If it quotes tier-0, also cite the Match Charting Project (CC BY-NC-SA).
   - Move the references below page 5. They do not count toward the limit [R4].
10. **The note's header gives the wrong reproduce command** [R12, R13]. It lists `python run_all.py --oos` and
    `python scripts/v2_burned_oos.py`.
    - The second script appends a new line to `results/oos_peeks.log` on **every** run and rewrites
      `data/v2_trades_is_oos.parquet`. Cite `bash reproduce.sh`, which the README already does.
    - `reproduce.sh` ends with `make_pdf.py`, which hard-codes the macOS Chrome path. Under `set -e` a Linux judge
      will see the script fail at its last step. Make that step optional, or say so in the README.
    - The note also contradicts itself: §2 says the forward window starts "after 2026-10-03 13:00 UTC" and Table 2
      says "from Oct 3 14:00 UTC". 14:00 is correct (amendment A1.6).
11. **Market eligibility** [R22; DP-rules: Devpost can disqualify a submission that "uses data not permitted for
    its track"].
    - Polymarket is not among the listed asset classes.
    - Ask in #ask-organizers or at **today's 5–6 PM check-in (Grand Ballroom)**, and keep the written answer.
    - Add one line to the note's data section on why it qualifies: a public order book, $2.84B traded in the
      universe, and public data with no keys.
12. **Unpushed work** [R18]. Anything the note, README or deck cites must be on `origin` before 11:00 EDT. Not yet
    pushed:
    - `1ebb458` (the rigor pack);
    - the modified `results/oos_peeks.log`;
    - untracked `research/v2/tier0/`, `results/tier0/`, `src/tier0.py`, `scripts/tier0_backtest.py`, `engine/`,
      `tests/test_engine_*.py`, `research/compliance/`, `research/v2/maker/` and `src/spin/`.

    Check the licence of `models/` (19 MB of vision weights) before committing it.
13. **Team actions.** List every member on Devpost [R15]. Sign up for a Sunday slot **today, 5:00–6:00 PM, Reitz
    Union Grand Ballroom** [R61]. The talk is Sunday 1:00–3:00 PM in the Matthews Suite, 5 minutes plus Q&A
    [R60]. Every member must be able to explain the strategy [R63].
14. **Integrity details a careful judge will find.** Fix them by adding lines, not by editing the
    pre-registration.
    - `HYPOTHESIS.md` says "Written 2026-10-03 ~10:15 UTC", but commit `7232986` is timestamped 09:50:47 UTC. It
      also names `src/split.py`, which does not exist; the split lives in `src/tape.py`. Add a line to
      DEVIATIONS.md saying the commit time is authoritative.
    - `COMPLIANCE.md` overclaims in three places: skew and worst month "in Table 2", a "daily stop" in §6 (the
      note has none), and cost doubling covered by slippage.
    - `DEVPOST.md` says "One command (bash reproduce.sh) regenerates every number". The tracking runs
      (HiPerGator) and the live-book numbers are not in `reproduce.sh`. It also quotes the OOS "+0.60¢" without
      "burned / non-blind".
    - README links `results/v2/forward.json` and `results/forward_peeks.log`, which do not exist yet.
15. **The deck is stale** (do not edit it; `build_deck.py` refuses to rebuild until the peeks settle).
    - Slides 7 and 12 say "3 lines" of OOS peeks; there are 14.
    - The title slide shows `github.com/OjasMishra32/courtside`, which is the backup remote, not the submission
      repo.
    - Slide 5 still has the FORWARD placeholder.

    Rebuild the deck once the log settles and the forward result is in.
16. **The variant count is out of date** [R9]. The note says 3,386. The rigor pack counts 3,410, which includes
    the 24-variant v2-safe grid. Also count anything run since: the 432 tier-0 counterfactual scenarios, the 5
    cost-stress scenarios, and any new lens such as `research/v2/maker/`.

---

## 3. Criterion by criterion

### C1. Economic Foundation: 8 / 10

- **For.** The counterparty is named: "Whoever is acting on an older tier." Persistence rests on physical gaps.
  The venue's own design corroborates it: a 1 s hold on sports orders, 3 s before May 2026.
- The rival stories were pre-registered and falsified. H1 (chase the move) loses −1.61¢ in sample and −2.08¢ out
  of sample. H2 shows prices calibrated within about 1¢, so slow money has no edge.
- H6 holds walk-forward: 8 of 8 months in sample and 3 of 3 out of sample, while everyone else loses. Copying the
  fast tier 3 s later loses too, which is direct evidence that the edge is speed.
- **Against.** The hypothesis behind the money (H6) was written after the in-sample wallet study (D4, D5). The
  note is honest about this, but the 10 band ("highly compelling and well-evidenced reasoning for the strategy's
  success") wants the traded claim tested cleanly.
- The note never gives the hypothesis in the track's template, and never says who the fast tier is.
- Its strongest blind evidence for the mechanism is in `research/v2/expand/RESULTS.md`, not in the note.

**Top 3 changes (all true repo content):**

1. **State the hypothesis in the template at the top of §1** [R21] (about 4 lines at 11 pt). Draft, from D5 and
   §1:
   > We expect Polymarket ATP/WTA moneylines to trade at stale prices for 1–3 s after each point, because
   > takers on slower tiers (score feeds 27–43 s late) trade against quotes faster tiers know are wrong. The edge
   > persists because the gaps are physical (frame rates, data licensing, stream delays) and the venue's 1 s
   > order delay protects makers. If true, wallets trading within 3 s of a detected score event should earn
   > positive net 30 s markouts month after month while all other takers lose. It fails if month-m net markout
   > is ≤ 0 in more than a third of months, or ≤ 0 out of sample. (H6: written after in-sample results, frozen
   > before OOS; D5.)
2. **Add the blind test of the mechanism** (2 lines). On 11,307 never-examined markets, fast-tier wallets beat
   all other takers by **+3.09¢ [2.89, 3.28] in sample and +2.16¢ [1.79, 2.53] out of sample** (causal window,
   match-clustered; `research/v2/expand/RESULTS.md`).
   - This is the cleanest evidence in the repo that the economic claim holds even where the v2 book does not.
     Today the note gives "+3.1¢ / +2.2¢" with no CI.
3. **Show the mechanism responding as theory predicts** (2 lines; move it up from §6 and D6). In-sample
   fast-tier edge by venue regime:
   - 3 s delay, no fee: 1.51¢
   - 3 s, 3% fee: 1.64¢
   - 1 s, 3%: 1.19¢
   - 1 s, 5%: 0.54¢

   Qualifying wallets also grew from 4 to 131 while the edge per share fell from about 2.4¢ to 0.8¢.
   - Less latency protection and more competition shrink the edge without killing it: the persistence argument
     backed by data.
   - Optionally add one labelled clause on who the fast tier is. Prints landing in the 0.5 s before a reprice are
     98% with the move, so some takers know the point 1–1.5 s before the book (§7). Courtside humans are an
     *inference* (`research/v2/tier0/RESULTS.md` §3).

### C2. Innovation: 8 / 10

- **For.** Several things here are uncommon in student work and in most desks' playbooks:
  - wallet-level, walk-forward identification of a latency tier from on-chain tapes;
  - a measured information ladder against official WTA point stamps: the book moves −1.2 s, the feeds +27 to
    +43 s;
  - a causal-window fix found by adversarial verifiers;
  - computer-vision lead times: 120 fps table tennis called 11 of 11 misses correctly 50 ms early; a Hawk-Eye
    class simulation gives ±2.4 cm at 100 ms; 25 fps broadcast is useless;
  - venue infrastructure measurements: Cloudflare's Miami edge, 67 ms one-way, an origin consistent with London.
- **Against (why not 10, "groundbreaking … distinct from conventional strategies").** Trading on faster sports data
  (courtsiding, latency arbitrage) is a known practice. The tennis Markov model is standard (Klaassen & Magnus).
- v2 is a filtered copy of fills that were already observed.
- The vision work is never linked to dollars in the note.
- The track also asks you to "say what is new" when you extend known work [R37].

**Top 3 changes:**

1. **Add two lines on what is new versus prior art** [R37]: on-chain wallet tiers, a ladder measured against the
   official clock, the causal window, and the order-delay time budget (an order must leave ≥ 1.3 s before the
   reprice, about 2.5 s before the official stamp). Cite courtsiding and Klaassen & Magnus as the base being
   extended.
2. **Connect the vision results to P&L with one sentence on the tier-0 counterfactual**, clearly labelled as
   assumed data (`research/v2/tier0/`; pre-registered at 17:25 UTC; commit it first).
   - Quote the driver, not the Sharpe: "the unmeasured official-stamp lag decides almost everything; the camera
     barely matters."
   - In-sample per-share edge: +3.22¢ under the pre-registered stale price, +2.09¢ under the nearer stale price.
   - Keep the 25 to 37 Sharpe figures out of the five pages. R35 says to "assume something is wrong" above 3, and
     these rest on assumed inputs.
3. **One line on the paper engine** (`engine/`, uncommitted; commit it with its tests first). It turns a vision
   call into Markov fair value, then into v2 risk limits, then into a paper executor that waits the venue delay
   plus measured latency.
   - Book reconstruction gave 0 mismatches against 3,882 snapshots on today's recording.
   - The engine is paper-only by construction.
   - This shows the idea runs end to end as software, without claiming live P&L.

### C3. Risk Management Plan: 7 / 10

- **For.** §6 covers the main risks:
  - venue rules, called the largest risk;
  - crowding;
  - a risk dial tested blind (v2-safe: worst day −$224 vs −$469);
  - hard limits: 100 net shares per match, $1k per order, capital 3× peak locked;
  - worst match −$206 (v1: −$3,098);
  - de-risking rules set in advance: halve below 0.3¢ trailing edge, stop at ≤ 0;
  - kill switches, settlement risk (2.9% settled 50/50), and legal and access limits.
- **Against (why not 9–10, "multiple contingencies and a thorough understanding of strategy risks").**
  - The biggest quantified risk is missing: out of sample, doubled fees erase the edge.
  - Concentration is not treated as a risk: out of sample the top 5 copied wallets carry 98% of U2 profit, and
    the wallet-clustered CI is [−0.60, 2.11].
  - There are no tail statistics.
  - The note does not say which controls were backtested (net cap, order cap, price zone, fee filter, hold to
    resolution) and which are deployment rules that were never simulated (P ≥ 0.95, kill switches,
    halve/stop).

**Top 3 changes:**

1. **Make doubled costs a named risk with a trigger** (2 lines). Use the numbers from §2 item 3: a fee near 10%
   at today's delay ends the strategy. Say the halve/stop rule exists for exactly this.
2. **Add tail and concentration lines** (2 lines).
   - Tail: skew 0.53 / 0.33, kurtosis 4.3 / 3.3, worst day −1.9% / −2.1%, worst month +$2.5k / −$434 (from
     `results/rigor/rigor.json` and `results/v2/causal.json`).
   - Concentration: the top 5 wallets carry 98% of OOS profit. The existing mitigation is monthly walk-forward
     requalification at the current fee with shrinkage (n0 = 200). No per-wallet cap was tested; say so.
3. **Split the controls into "backtested" and "deployment only"** (1–2 lines).
   - The net cap bounds the payoff swing per match at 100 shares, i.e. $100.
   - The worst realised match was −$206.
   - Add the **$1,000 daily stop** (about 2× the worst in-sample day) and the kill switches as implemented in
     `engine/risk/limits.py`. `COMPLIANCE.md` already claims a daily stop. The halve/stop rule is a rule, not a
     backtest result.

### C4. Liquidity & Capital: 6 / 10

- **For.** The market measurements are first rate:
  - median 1¢ spread, $8.1k at the touch and $61k within 2¢;
  - stale depth per point: median $222–565, gone 0.5 s after the reprice;
  - an oracle bound of +$18–21 per point;
  - the time budget behind the 1 s delay;
  - v2 notional of $1.48M over 206 days on $28k of capital, with fast-tier volume of $0.3–3.1M a month.
- **Against (R41, outline item 10: "Roughly how much capital the strategy could run before the edge erodes").**
  - There is no single capacity figure in dollars.
  - Position size is never expressed against volume.
  - There is no cost in bps and no doubled-cost line.
  - The note itself says the edge is gone at +½ tick out of sample and that deployment needs in-venue tracking,
    a co-located gateway and a permitted venue. That falls short of the 7–9 phrase "realistic and practical
    deployment".

**Top 3 changes:**

1. **Add a "Costs" paragraph** [R30, R31] (3 lines; it also serves C3 and C5). Draft:
   > Costs: each match's own taker fee, rate·q(1−q) per share (≈120 bps of notional in sample, ≈179 bps out of
   > sample at 5%), and the traded spread (median 1¢ at entry), paid on side-of-book prints. Doubling the fee
   > leaves +0.77¢ in sample (7/7 months) but −0.34¢ [−0.86, 0.19] out of sample (0/3). Doubling fee and spread
   > gives +0.27¢ (Sharpe 3.0) and −0.84¢. In today's regime the edge does not survive doubled costs.
2. **Give capacity as a frontier, not just adjectives** (3-row table or 2 lines, labelled "onset window,
   pre-D9"). From `research/v2/sizing/RESULTS.md`, 1 s/5% regime, per 30 days:

   | Capital | Notional | Sharpe |
   |---|---|---|
   | $23k | $259k | 16.8 |
   | $79k | $1.10M | 6.6 |
   | $102k | $1.65M | 6.0 |

   Then add one sentence on scale:
   - Today's v2 runs about $7.2k a day, roughly 0.09% of the $7.9M a day of tennis volume (my arithmetic on
     note numbers).
   - That is about $215k a month against $0.3–3.1M of fast-tier volume in the 0–3 s window. Scaling up means
     displacing the existing fast tier, so the limit is queue position, not book depth.
3. **Give size against liquidity, and the deployment path, in 2 lines.**
   - The median v2 trade is about $11 in sample and $16 out of sample (mean $27 / $31), under 1% of the $8.1k at
     the touch, and capped by the copied print. These are my figures from the trades parquet; have a script
     print them.
   - Then name the deployment requirements with their measured numbers: a signal ≥ 1.3 s before the reprice, a
     co-located gateway (saves about 130 ms per round trip), and a permitted venue (the international venue
     restricts US persons).
   - Kalshi's 0.07·p(1−p) fee leaves the hedged laggard at +0.06¢ [−1.17, 1.48] (`research/v2/kalshi/`).

### C5. Performance & Analytical Evidence: 7 / 10 (cap risk 4)

- **For.** The analysis is genuinely deep:
  - in-sample and out-of-sample results kept separate, net of each match's own fee;
  - CIs clustered by match;
  - monthly walk-forward;
  - +½ and +1 tick slippage stress;
  - a factor regression (alpha t = 8.5, R² = 3%);
  - a pre-registered blind test on 11,307 markets, reported as a **fail**;
  - a pre-registered forward test;
  - verifiers who found and fixed a hindsight bug (D9);
  - the variant count disclosed;
  - an equity curve spanning both periods (Fig. 2).

  The repo also holds results the note does not use (`research/rigor/RESULTS.md`): a DSR of 0.997 in sample at
  N = 3,386, a block-bootstrap Sharpe CI of [11.9, 17.4] in sample and [1.9, 12.3] out of sample, and a PBO of 0%
  on the sizing grid.
- **Cap risk** [R53: capped at 4 "if they find lookahead bias or tuning on the out-of-sample period"]. Three
  things can trigger it:
  - **Same-print fills.** Table 2 fills at the fast tier's own print. Read against "Lag every signal at least
    one bar", trading at the price of a print you only know exists because it happened looks like lookahead.
    The note frames it as an opportunity measurement ("paper book on the fast tier's own fills"), but never ties
    that to the lag rule. The lagged, executable copy (+3 s) loses every month.
  - **v2 designed after the OOS was opened.** v2 was designed after v1's OOS result was seen. It is labelled
    "burned", but a strict judge can still call that tuning on the OOS.
  - **Reproduction.** Judges must fetch data for 1–2 hours before `reproduce.sh` runs, so the spot check can
    fail for practical reasons.
- **Against, beyond the cap.**
  - Annualized return, volatility and out-of-sample turnover are missing.
  - The burned-OOS DSR is weak: 0.48 at N = 44 and 0.075 at N = 3,386.
  - Out of sample the result depends on a handful of wallets.

**Top 3 changes:**

1. **Defuse both cap triggers in the text** (3 lines under Table 2). Say plainly:
   - Table 2 is the opportunity at the fast tier's speed. Its fills are the contemporaneous fast-tier prints, so
     it is not a lagged copy strategy.
   - The lagged copy (+3 s) loses in every month (Table 1).
   - Wallet qualification, the price filter and the window use only past data and detection time (D9).

   Lead the results with the clean out-of-sample numbers, then label the burned window:
   - v1: −$36k;
   - H6: 3 of 3 months;
   - U2 blind: a fail at +1.22¢ [−0.19, 2.65];
   - forward: the Sunday result;
   - v2 burned OOS: +0.60¢ (non-blind).

   Add the peeks sentence:
   > OOS looks (`results/oos_peeks.log`): v1 once, blind; two first runs of pre-registered blind tests on unseen
   > markets; 11 non-blind looks at the burned window (v2 ×2, v2-safe ×1, cost stress ×1, tier-0 counterfactual
   > ×7). The only change after a look was the D9 causal-window fix, which lowered burned-OOS v2 from +0.75¢ to
   > +0.60¢.
2. **Complete the minimum metrics and the Sharpe context in Table 2** [R7, R35] (about 4 rows; every number
   printed by a script in `reproduce.sh`):

   | Metric | In sample | Burned OOS |
   |---|---|---|
   | Ann. return / vol (on capital) | 253% / 17.5% | 148% / 22.2% |
   | Turnover | 93× a year | 129× a year |
   | Skew / worst day / worst month | 0.53 / −1.9% / +$2.5k | 0.33 / −2.1% / −$434 |
   | Fee ×2 / costs ×2 | +0.77¢ / +0.27¢ | −0.34¢ / −0.84¢ |

   Then one line of rigor: DSR 0.997 in sample at N = 3,386, and 0.48 out of sample at N = 44 (0.075 at
   N = 3,386); bootstrap Sharpe CI [1.9, 12.3] out of sample.
3. **Make the judge's spot check cheap** [R13, R54].
   - Put `bash reproduce.sh` in the note header.
   - State in the README how long each step takes: fetch about 1–2 h; the 12 committed tests pass in about
     2.3 min locally.
   - List what is not reproduced by `reproduce.sh`: the HiPerGator tracking and the live-book recordings, with
     the scripts that made them and their cached outputs.
   - Before 11:00, re-run `reproduce.sh` on a clean checkout and diff `results/` against the note. The last full
     run logged was 09:47. Cost stress and the rigor numbers were added after it.
   - Optional, if the Polymarket API terms allow: commit a small derived file (the v2 trades parquet is 14 MB)
     plus a 10-second script that recomputes Table 2, so a judge can check it without the 1–2 h fetch.

---

## 4. Fitting the fixes into 5 pages at 11 pt

Measured by rendering `docs/NOTE.md` with modified copies of the `make_pdf.py` CSS in my scratchpad. The repo
files were unchanged.

| Layout | Pages |
|---|---|
| As built (10 pt / 8.3 pt, 0.6 × 0.65 in) | 5.0 (last page about half full) |
| 11 pt everywhere, 1 in margins, line-height 1.38 | **6.23** |
| 11 pt everywhere, Word "Moderate" (1 in top and bottom, 0.75 in sides), line-height 1.3 | **5.61** |

Savings measured at 11 pt and 1 in margins:

| Cut | Pages saved |
|---|---|
| Latency table (§5) to the appendix | 0.53 |
| Fig. 1 to the appendix (Table 1 already carries its numbers) | 0.41 |
| Fig. 2 at 70% width | 0.14 |
| References below page 5 (they don't count) | 0.04 |

**Plan.** Use 11 pt for body, tables and captions, 1 in margins (safest) or "Moderate" at the least, and
line-height 1.3.

- **Cut about 1.1 pages:** the latency table and Fig. 1 to the appendix, Fig. 2 at 70%, references out.
- **Trim about 0.3 more:**
  - the "paper book on the fast tier's own fills" point appears three times (§4 twice, §8 once); keep one;
  - shorten the maker-exits paragraph to one line;
  - tighten the §7 per-point paragraph and the §2 bullets.
- **Add about 0.45 back:**
  - a 0.2-page Summary with the headline OOS results [R10];
  - the template sentence;
  - the costs paragraph;
  - the peeks sentence;
  - 4 new Table 2 rows;
  - the data-problems line.

Every claim that matters must stay in the five pages. The appendix may go unread [R4]: keep one sentence of the
latency result ("the book reprices 1.2 s before the official stamp; public feeds trail by 27–43 s") in the body.

**Rename the headings to the track's outline** [R10, R58] so each judge finds the section that feeds their
criterion. This costs no space:

Summary · Economic Hypothesis · Data & Universe · Methodology · Results · Risk Management · Liquidity &
Capacity · Limitations & Next Steps

**Verify after every rebuild:**
`.venv/bin/python scripts/make_pdf.py && .venv/bin/python -c "import pymupdf;print(len(pymupdf.open('docs/NOTE.pdf')))"`
Also check the smallest font size in the PDF:
`.venv/bin/python -c "import pymupdf;print(min(s['size'] for p in pymupdf.open('docs/NOTE.pdf') for b in p.get_text('dict')['blocks'] for l in b.get('lines',[]) for s in l['spans'] if s['text'].strip()))"`
It should print ≥ 11. Text inside the figure images is not counted.

---

## 5. The ten hardest questions, with the best honest answer from the repo

**Q1. Table 2 fills at the fast tier's own print. You only know that print exists because it happened. Isn't that
lookahead, and isn't this someone else's P&L?**
- Yes, it is their speed, and we say so. Table 2 measures the opportunity for a trader as fast as the fast tier.
  It is not our execution (NOTE §4, §8).
- What gets counted uses no future information. Wallets qualify on past months only, the fee filter uses the fee
  at the time, and the 0–3 s window runs from *detection*, not from the onset seen in hindsight (D9).
- The executable lagged version, copying the same trades 3 s later, loses in every month in and out of sample
  (Table 1). That is our evidence the edge is speed.
- Out of sample it is gone at +½ tick: +0.10¢ [−0.41, 0.63]. Second place earns nothing.
- Our own route to first place is a tier-0 signal. We only model it, as a labelled counterfactual with assumed
  data.

**Q2. You built v2 after v1 lost $36k out of sample. Isn't that tuning on the out-of-sample period?**
- The OOS was opened once, blind, for v1 at 10:42 UTC, and v1's loss is reported.
- v2's rules were tuned on in-sample data only (six lenses, `research/v2/`). But the motivation came from how v1
  failed (big tickets on cheap tokens). So we call that window burned and label every v2 number on it non-blind
  (HYPOTHESIS_V2.md).
- v2's clean tests are pre-registered:
  - The blind test on 11,307 never-examined markets: +2.02¢ [1.14, 2.93] in sample, a pass; +1.22¢
    [−0.19, 2.65] out of sample, a **fail** by our rule.
  - The forward window from Oct 3 14:00 UTC, run once on Sunday.
- All 14 looks are in `results/oos_peeks.log`.

**Q3. A Sharpe of 14.5 on daily data. The brief says above 3, assume a bug.**
- We assumed one and found one: the onset hindsight (D9). Fixing it cut in-sample Sharpe from 16.8 to 14.5 and
  burned-OOS per-share edge from +0.75¢ to +0.60¢.
- What remains is structural. v2 places about 270 small bets a day (55,662 in 206 days), each settled by an
  exogenous binary outcome, with net exposure capped at 100 shares per match.
- The tails are mild: skew 0.53, kurtosis 4.3, worst day −1.9%, no losing month in sample.
- The return is what the edge implies. 2.73¢ per $ on about $7.2k a day is about $196 a day, about 0.7% of $28k
  of capital.
- It falls fast with costs:

  | Case | Sharpe |
  |---|---|
  | +½ tick | 9.8 |
  | +1 tick | 4.3 |
  | All costs doubled | 3.0 |
  | Burned OOS (bootstrap CI [1.9, 12.3]) | 6.7 |

**Q4. What happens when costs double? What is your cost in bps?**
- Fees are each match's own rate·q(1−q): about 120 bps of notional in sample (mixed 0/3/5% regimes) and about
  179 bps out of sample (all 5%).
- The spread is paid as traded: median 1¢ at entry.
- Doubling the fee: +0.77¢ in sample (7 of 7 months), but **−0.34¢ [−0.86, 0.19] out of sample (0 of 3
  months)**. Doubling the fee and adding a half-spread: +0.27¢ (Sharpe 3.0) and −0.84¢.
- So in today's regime the edge does not survive doubled costs, and we say so. That is why venue rules are the
  first risk in §6, and why the halve/stop rule exists.

**Q5. Is Polymarket even allowed in this track, and can you trade it from the US?**
- The track allows "Any liquid, publicly traded market". Polymarket tennis has a public order book, public data
  with no keys, and $2.84B traded in our universe.
- *Team: get the organizers' written confirmation today and cite it here.*
- The international venue restricts US persons, and the note says so. The repo only reads public data and never
  places an order (TERMS 5.3). The engine is paper-only by construction. A deployment would need a permitted
  venue, licensed data and legal review.
- We tested Kalshi, the alternative. It leads about 69% of repricings, but at 0.07·p(1−p) the hedged laggard
  trade nets +0.06¢ [−1.17, 1.48].

**Q6. Who is the fast tier, and why hasn't competition killed the edge?**
- We can't identify them. We can characterize them:
  - they trade within 3 s of a detected point;
  - selected walk-forward, they beat the market in 8 of 8 in-sample and 3 of 3 out-of-sample months;
  - on unseen ITF markets they beat everyone else by +3.09¢ [2.89, 3.28] in sample and +2.16¢ [1.79, 2.53]
    out of sample.
- Prints landing in the 0.5 s before a reprice are 98% with the move, so someone knows the point 1–1.5 s before
  the book. Courtside humans would imply an official-stamp lag of about 3.1 s, but that is an inference, not a
  measurement.
- Competition is biting. Qualifying wallets grew from 4 to 131 and the edge per share fell from about 2.4¢ to
  0.8¢. The move from a 3 s delay and 3% fee to 1 s and 5% cut it from 1.64¢ to 0.54¢.
- It shrank but stayed positive in every month, which is what the persistence argument predicts.

**Q7. You tried 3,386 or more variants. Why isn't this the luckiest draw?**
- Every variant is counted and reported (§8, `research/v2/`).
- The deflated Sharpe at N = 3,386 is 0.997 in sample, even under the most conservative variance.
- On the 40-day burned OOS it is 0.48 at N = 44 and 0.075 at N = 3,386. So 40 days cannot rule out luck at the
  full trial count, and we say that.
- The probability of backtest overfitting is 0% on the 55-policy sizing grid, and 15% (by Sharpe) on the
  24-variant v2-safe grid.
- The trial count overstates independent trials, because many variants are near-duplicates. The real answer is
  the forward test.

**Q8. Your OOS is 20% of matches but only 38 of 360 days, and your universe keeps matches with at least $5k of
lifetime volume, which you only know afterwards. Isn't that survivorship and lookahead?**
- We read "20% of your history" as 20% of observations: 2,617 of 13,084 matches, 21% of volume. By calendar
  time it is 38 days; a time-based 20% would start on Jul 23. The note should say which reading we used.
- The volume filter is ex-post. It drops thin markets that a live trader would still see.
- Our check is the blind U2 test on 11,307 other markets (≥ $1k, mostly ITF). The fast-tier gap holds there.
  v2 is +2.02¢ in sample and +1.22¢ out of sample, where the CI includes 0.
- H1–H6 use onset-aligned windows: an ex-post event study, labelled as such. Every tradable v2 number uses the
  causal window.

**Q9. How much capital could this run, and doesn't it hang on five wallets?**
- Not much. v2 ran about $7.2k a day of notional ($1.48M in 206 days) on $28k of capital (peak locked $9.4k),
  with a median trade of about $11.
- Capacity is bounded by the fast tier's own prints, not book depth. On the sizing frontier (onset labels, per
  30 days), $23k of capital trades $259k at Sharpe 16.8, and $102k trades $1.65M at Sharpe 6.0.
- Live stale depth per point is a median $222–565, gone 0.5 s after the reprice.
- Concentration is real. Out of sample the top 5 copied wallets carry 98% of U2 profit, and the wallet-clustered
  CI on the burned OOS is [−0.60, 2.11]. That is why we say v2 is "positive but not proven".

**Q10. What does the computer vision add? Your own counterfactual says the camera barely matters.**
- It measures what tier 0 can know:
  - 120 fps video called 11 of 11 table-tennis misses correctly 50 ms before contact (recall 27%, Wilson lower
    bound 74%);
  - a Hawk-Eye-class simulation gives ±2.4 cm 100 ms before the bounce;
  - 25 fps broadcast is useless.
- Against a 1 s order delay those leads are small. The pre-registered counterfactual (assumed feed, not bought)
  finds that the unmeasured official-stamp lag dominates.
- The honest contribution is the time budget: an order must leave ≥ 1.3 s before the reprice, about 2.5 s before
  the official stamp. The vision work shows where a lead comes from (frame rate, cameras, being in the venue).
- We have not shown a tier-0 order reaching a stale quote end to end.

**Also be ready for:**
- **"Can we run it?"** `scripts/fetch_polymarket.py` (public, no keys, about 1–2 h), then `bash reproduce.sh`.
  The 12 committed tests pass in about 2.3 min. Tracking and live recordings are cached, not re-run.
- **"Why 3× peak locked capital?"** Fixed before OOS (D6), with a 4 h ex-ante lock per position (A1.3). Peak
  locked is ex-post. Sharpe and dollar P&L don't depend on it; percentage returns do.
- **"A forward test of under a day?"** Primary A tests the economic claim. Primary B may be underpowered, and A1.5
  says so in advance. Both are reported either way.

---

## 6. Every requirement, item by item (R1–R73)

Status values:

| Status | Meaning |
|---|---|
| OK | met |
| PART | partly met |
| FIX | not met |
| RISK | judgment call |
| TEAM | a team action |
| INFO | nothing to do |

| R | Requirement (short) | Status | Where it stands |
|---|---|---|---|
| 1 | Note PDF + public repo link, both | TEAM | Both exist. Repo returned HTTP 200 at 14:15. Submit both on Devpost. |
| 2 | ≤ 5 pages incl. figures/tables | RISK | 5 now; 6.23 at 11 pt with 1 in margins (§4) |
| 3 | 11 pt+, standard margins | FIX | 10 / 8.3 / 8.5 pt; 0.6 × 0.65 in |
| 4 | Appendix may go unread | OK | Keep every key claim in the body if tables move |
| 5 | Hypothesis before results | OK | §1 comes before §3. Commit `7232986` (09:50 UTC) precedes the pipeline commit (10:15 UTC). |
| 6 | IS / OOS separate, net of costs | OK | Tables 1–2 |
| 7 | Ann. return, vol, Sharpe, max DD, turnover, equity curve, both periods | PART | Return and vol missing; OOS turnover missing (§2 item 4) |
| 8 | Risk and liquidity sections | OK | §6, §7 |
| 9 | Variant count disclosed | PART | Stale (§2 item 16) |
| 10 | Suggested outline | PART | No Summary or Limitations heading; headings don't match (§4) |
| 11 | Public repo, README, dependency file | OK | `requirements.txt` pins 9 packages. Deck needs python-pptx; tracking needs the HiPerGator stack. Say so. |
| 12 | README setup, single command, all code, data instructions | PART | Live-book recordings can't be re-downloaded; say how they were made (`src/live_recorder`) |
| 13 | One command reproduces headline numbers | PART | `reproduce.sh` exists, but the note header cites other commands; the PDF step is macOS-only |
| 14 | No keys or licensed raw data committed | OK | `.env` and `data/` gitignored; scan of 497 tracked files found no key patterns |
| 15 | All team members on Devpost | TEAM | |
| 16 | Every source cited | FIX | §2 item 9 |
| 17 | Disclose pre-existing components | PART | BlurBall weights and TrackNet detectors appear in DEVPOST.md and READMEs. Name them as pre-existing on Devpost (HG says pre-existing work is "not allowed"; TERMS 14.2 allows disclosed components). |
| 18 | Push until 11:00 | TEAM | §2 item 12 |
| 19 | Edge written before any backtest | OK | Pre-registration at 09:50 UTC; first data/strategy commit at 10:15 UTC |
| 20 | Hypothesis committed first | OK | The "~10:15 UTC" text and `src/split.py` typos need a DEVIATIONS line |
| 21 | Template (universe … falsifier) | PART | §3, C1 change 1 |
| 22 | Liquid, publicly traded market | RISK | Polymarket is not among the chips; get written confirmation |
| 23 | Free public data allowed | OK | Polymarket and Kalshi public APIs, no keys |
| 24 | Holdout = last 20% or 2 years, whichever is shorter | OK / RISK | 20% of matches (2,617; 21% of volume) is only 38 of 360 days. State the interpretation. |
| 25 | Set holdout aside early | OK | `data/locked/`; frozen in `9d61d1b` (10:32 UTC) before opening at 10:42 UTC |
| 26 | Evaluate once | PART | Once for v1; v2 labelled burned and non-blind (cap risk, §3 C5) |
| 27 | Report OOS good or bad, and every peek | PART | v1's loss reported; peeks not itemised in the note (§2 item 5) |
| 28 | Walk-forward inside IS, purge gap | PART | Monthly walk-forward OK. No purge is stated; labels are 30 s markouts or resolution. Say what you did. |
| 29 | Lag signals; trade next bar | RISK | Causal window, venue delay and our latency are applied. But Table 2 fills at the copied print; disclose it (§3 C5). |
| 30 | Cost in bps, justified | FIX | §2 item 6 |
| 31 | Costs doubled; say if the edge disappears | FIX | In the repo, not in the note; the OOS edge disappears |
| 32 | Survivorship, corporate actions, missing data explained | FIX | §2 item 8 |
| 33 | Variant count, plateau, DSR | OK | §8 plus the rigor pack (bring one line in) |
| 34 | Few parameters, economic reason | OK | v2 has 5 rules, frozen on IS |
| 35 | Max DD, skew, worst month next to Sharpe; Sharpe > 3 explained | PART | Explanation present; skew and worst month missing |
| 36 | By year or regime | OK | Monthly bars (Fig. 2) and fee/delay regimes (D6) |
| 37 | Extend and cite; say what is new | PART | §3 C2 change 1 |
| 38 | AI tools allowed; explain every line | TEAM | Heavy agent and verifier use. Every member must be able to explain the code (§5). |
| 39 | Any language | INFO | Python |
| 40 | Simple explanation first; factor regression | OK | Alpha t = 8.5, betas insignificant, R² = 3% |
| 41 | Size vs ADV, capacity in $, costs ×2 | PART | §3 C4 |
| 42 | Limits, de-risking, tail/regime | PART | §3 C3 |
| 43 | Keep the failures | OK | Five failed ideas reported |
| 44 | No funded accounts | OK | Read-only; engine refuses live trading |
| 45 | Licences / ToS | PART | Credit Match Charting Project (CC BY-NC-SA) if tier-0 is committed; OpenTTGames is credited |
| 46 | Judges may re-run, including on held-out data | OK | `scripts/forward_test.py` takes `--start` |
| 47 | 5 × 10 scoring, bands | INFO | |
| 48–52 | The five criteria | INFO | Scored in §1 and §3 |
| 53 | Criterion 5 cap | RISK | §3 C5 |
| 54 | Code supports criterion 5 | PART | 12 committed tests pass. The last full reproduce run was 09:47, before cost stress and rigor were added; re-run on a clean checkout. |
| 55 | Tie-break: Performance, then EF | INFO | Protect criterion 5 first |
| 56 | No P&L leaderboard | OK | The note's candour fits "a Sharpe of 0.6 you can defend" |
| 57 | Hypothesis up front, fair test, failures, code that runs | PART | Fair test: OOS burned for v2. Code: 1–2 h fetch. |
| 58 | Sections feed criteria | PART | Rename the headings (§4) |
| 59 | Judges, finality; Massive bonus | INFO | Massive not entered: no 8-K or options data |
| 60 | 5-min talk + Q&A, Sun 1–3 PM, Matthews Suite | TEAM | Deck timed for about 4:40 with 5 backups |
| 61 | Slot sign-up today 5–6 PM, Grand Ballroom | TEAM | **Today** |
| 62 | Presentation format unspecified | TEAM | Ask at check-in |
| 63 | Everyone can explain | TEAM | Rehearse §5 |
| 64 | Deadline Sun Oct 4, 11:00 AM EDT, Devpost and code | TEAM | Re-verified live at 14:13 EDT |
| 65 | Changed today | INFO | Confirmed: only the 4 deadline strings changed on TP |
| 66 | Devpost window, winners | INFO | |
| 67 | Team size, in-person, one track, rosters locked | TEAM | |
| 68 | Eligibility (18+, enrolled, ID) | TEAM | |
| 69 | Rule changes via Discord / HG | TEAM | Watch #announcements |
| 70 | Code of Conduct | OK | |
| 71 | Back up your work | OK / TEAM | The backup remote exists, but unpushed work is not backed up |
| 72 | Prizes | INFO | |
| 73 | Submit even if unfinished | TEAM | Submit by 11:00 even if the forward test is late |

---

## 7. Timeline (Eastern)

| When | What |
|---|---|
| **Today, 5:00–6:00 PM, Grand Ballroom** | Sign up for a presentation slot. Ask organizers: (1) is Polymarket allowed? (get it in writing); (2) the presentation format; (3) where is the Participant Brief? (4) do they have a reading of "standard margins"? |
| Tonight | Edit NOTE.md per §2–§4. Have scripts print every new number. Rebuild and check pages and font size. Push everything the note cites. Update COMPLIANCE.md, DEVPOST.md and README. |
| Sun about 07:30 | Run the forward test once. Fill Table 2 and the deck. Rebuild the note PDF and the deck (once the peeks settle). |
| Sun by about 10:30 | Re-run `reproduce.sh` on a clean checkout and diff against the note. Make the final push and the Devpost submission with the PDF, repo link and all members. Hard stop: **11:00 AM**. |
| Sun 1:00–3:00 PM, Matthews Suite | 5-minute talk plus Q&A. Use §5. |
