# COURTSIDE vs the Systematic Trading track: compliance audit

This audit checks all 73 items in `research/compliance/REQUIREMENTS.md` against the submission.

**Snapshot.** Audited Sat 2026-10-03, 14:15–14:25 EDT, read-only.
- Repo HEAD is `1ebb458` (14:12 EDT, the rigor pack). It has **not been pushed**: origin/main is still `4ba8e88`. The public GitHub API reports the repo as `"visibility": "public"`, with its last push at 18:02Z.
- The working tree has uncommitted changes:
  - `results/oos_peeks.log` (line 13).
  - Untracked paths: `engine/`, `models/`, `src/tier0.py`, `src/spin/`, `scripts/tier0_backtest.py`, `scripts/spin_tennis_*.py`, `research/v2/tier0/`, `research/v2/maker/`, `results/tier0/`, `results/spin/`, `results/engine/`, `tests/test_engine_*.py`, `hpg/engine_vision.sbatch` and `research/compliance/`.
- Commits landed while the audit was running. Re-check any row that cites a file against the HEAD you actually submit.

**Live site check (about 14:17 EDT).**
- The track page still loads the same chunks that REQUIREMENTS.md was built from: `SystematicTrackPage-tcbiXROm.js`, `shell-Di37dqBY.js` and `index-CNWGO2eT.js`. The rules text has not changed since 14:10.
- Spot-checked strings that are present in the live chunk: "11pt", "whichever is shorter", "capped at 4", "bps per trade", "costs double", "Report every peek", "purge gap" and "Participant Brief".
- Deadline:
  - The shell clock is `Date.UTC(2026,9,4,15,0,0)`, which is **11:00 EDT**.
  - The Devpost header says "Deadline: Oct 4, 2026 @ 11:00am EDT".
  - Devpost /details/dates says "Submissions … October 04 at 11:00am EDT".
  - "10:00 AM" no longer appears in the track or shell chunks. Its only remaining use on the home page is Saturday's MLH workshop.
- **New fact, not in REQUIREMENTS.md:** the gqhacks.com home page lists **Polymarket as an event sponsor**, with a logo linking to polymarket.com in the sponsor list next to Jane Street and Citadel Securities. This helps item 22, but it is not a ruling.

**PDF check.** The task asked for a rebuild with `scripts/make_pdf.py`. To avoid touching tracked files, the rebuild was done in the scratchpad.
- The committed `docs/NOTE.pdf` has **5 pages**. Its extracted text is identical to a fresh build from `docs/NOTE.md`.
- Measured format, with PyMuPDF and `scripts/make_pdf.py` L9–L22:
  - Letter paper, margins **0.6 in × 0.65 in**.
  - Body text **10 pt**, tables **8.3 pt**, captions and code **8.5 pt**.
  - Page 5 ends at 410/792 pt.
- Re-flow tests of the same text:

  | Body font | Tables/captions | Margins | Pages |
  |---|---|---|---|
  | 11 pt | unchanged | 1 in | **6** |
  | 11 pt | 11 pt | 1 in | **7** |
  | 11 pt | 11 pt | 0.75 in | **6** |

**Status key.**
- MET: the submission satisfies the item now.
- PARTIAL: the submission addresses the item, but there is a gap a judge could find.
- MISSING: the submission does not address the item.
- USER-ACTION: only a person can do it (Devpost, the organizers, a room, a push).
- N/A: the item is informational and there is nothing to check.

**Tally:** MET 24 · PARTIAL 24 · MISSING 2 · USER-ACTION 14 · N/A 9.

---

## Fix first (ranked by score impact)

1. **Item 3, font and margins: MISSING.** The note is built at 10 pt body and 8.3 pt tables, with 0.6 in margins. At 11 pt with standard margins the same text runs to 6–7 pages, so 1–2 pages must be cut or moved *before* adding the fixes below. Candidates to cut:
   - Shrink the §5 latency table to two sentences.
   - Drop the two context rows of Table 1.
   - Shorten the tracking bullets in §2.
   - Move the references below a "References" heading after page 5, since references don't count.

   Don't move anything that matters into an appendix, because judges may skip it.
2. **Item 31, costs doubled: MISSING from the note, and the out-of-sample edge disappears.** The results already exist in `results/v2/cost_stress.json`, produced by `scripts/v2_cost_stress.py`, which runs from `reproduce.sh` L8. The rule says "If the edge disappears, say so." `docs/COMPLIANCE.md` L29 wrongly maps this rule to the ½-tick and 1-tick slippage rows.

   | Net ¢ per share, 95% CI | In sample | Burned OOS |
   |---|---|---|
   | Base | +1.38 [1.17, 1.59] | +0.60 [0.09, 1.13] |
   | Fees ×2 | +0.77 [0.57, 0.98] | **−0.34 [−0.86, 0.19]** |
   | All costs ×2 | +0.27 [0.07, 0.48] | **−0.84 [−1.36, −0.31]** |

3. **Unfilled forward-test placeholders in the note.** `[FWD_N]`, `[FWD_RES]`, `[FWD_PNL]`, `[FWD_A]` and `[FWD_B]` sit at `docs/NOTE.md` L87–95. The note also contradicts itself on when the forward window starts: L34 says "after 2026-10-03 13:00 UTC" and L85 says "from Oct 3 14:00 UTC". Amendment A1 in `HYPOTHESIS_V2.md` (L62–64) fixed it at 14:00.
4. **Item 53, the score cap on criterion 5.** Three exposures:
   - (a) The last logged end-to-end reproduction is `reproduce.log` at 09:47 EDT, before the D9 causal fix (845666f, 09:55). Re-run `bash reproduce.sh` on a clean clone and diff the numbers against Table 2.
   - (b) The v2 book fills at the **same print** that generates its signal, the fast tier's own fills (NOTE L114–115, L186–187). A judge could read that as lookahead (item 29).
   - (c) v2 was designed knowing that v1 lost on the OOS window (NOTE L32–33, HYPOTHESIS_V2 L6–9). A judge could read that as "tuning on the out-of-sample period" (item 26).
5. **Items 7 and 35, metrics.** The note is missing annualized return and volatility for both periods, turnover for the OOS period, and skew and worst month next to Sharpe. The values are in the table below.
6. **Items 22 and 61, today (Saturday).**
   - Get written confirmation that Polymarket is an allowed market for this track. Ask in #ask-organizers on Discord or at the check-in.
   - Sign up for a presentation slot at the **5:00–6:00 PM Track Check-ins in the Reitz Union Grand Ballroom**. The live home page schedule says "Track Check-ins · Grand Ballroom · sign up for a Sunday presentation slot".
7. **Items 12, 18 and 71, the repo.**
   - Push `1ebb458`.
   - `results/oos_peeks.log` lines 4–5, 9–11 and 13 record OOS reads by tier-0 code (`src/tier0.py`, `scripts/tier0_backtest.py`, `research/v2/tier0/`). That code is untracked. Either commit it, labelled as a counterfactual, or explain in DEVIATIONS why those reads exist without code in the repo.

### Numbers available for the fixes (auditor-computed; add them to a committed script before quoting)

These were computed from `results/v2/causal.json` (capital = 3× peak locked) and `research/rigor/out/daily_series.csv`. They are **not yet produced by any committed script**. Generate them in code first, so the note matches what the code outputs (item 13).

| v2, causal window, net | In sample (206 days) | Burned OOS (40 days) |
|---|---|---|
| Annualized return: mean daily P&L ÷ capital × 365 (arithmetic) | 253% | 148% |
| Annualized volatility: daily sd × √365 | 17.5% | 22.2% |
| Sharpe (cross-check; matches the note) | 14.48 | 6.67 |
| Turnover: $ traded ÷ capital, annualized | 92.6× | 129.3× |
| Daily skew (`research/rigor/RESULTS.md` §1) | 0.53 | 0.33 |
| Worst month (`causal.json`) | +$2,543 | −$434 (October is partial) |
| Net edge per $ traded (`per_usd_c`) | 2.73¢ = **273 bps** | 1.14¢ = **114 bps** |
| Taker fee, in bps of notional | 10,000 × rate × (1−q) = 250 bps at q = 0.5, 50 bps at q = 0.9 (5% rate) | same |

---

## A. Submission artefacts

| # | Requirement | Status | Evidence | Gap or fix |
|---|---|---|---|---|
| 1 | Note PDF and public repo link on Devpost; both required | USER-ACTION | `docs/NOTE.pdf` exists (5 pp). The repo is public (GitHub API `visibility: public`, HTTP 200). | Upload the PDF *file* to Devpost; `docs/DEVPOST.md` L60 only lists a repo path. Paste the repo URL. |
| 2 | ≤ 5 pages, figures and tables included | MET (as built) | 5 pages, measured. Page 5 ends at 410/792 pt. | Holds only at the current non-compliant format (item 3). Recheck after every rebuild. |
| 3 | 11 pt or larger, standard margins | **MISSING** | `scripts/make_pdf.py` L9 `margin: 0.6in 0.65in`; L10 body `10pt`; L17 tables `8.3pt`; L16, L22 code and captions `8.5pt`. | Use ≥ 11 pt body (tables ideally too) and 1 in margins. That adds 1–2 pages, so cut content (see Fix 1). |
| 4 | References and appendix don't count; the appendix may go unread | MET | No appendix. References are inline in §8, L189–191. | Moving the references below page 5 frees about 4 lines. Keep anything material in the 5 pages. |
| 5 | Hypothesis stated before results | MET | §1 (L5–20) comes before §3 (L40). It cites `HYPOTHESIS.md`, commit `7232986`. | none |
| 6 | IS and OOS reported separately, net of costs | MET | Table 1 L44–51 and Table 2 L85–95: separate IS and OOS columns, net of each match's fee and traded spreads (L25–28). | The forward column is still placeholders (Fix 3). |
| 7 | Annualized return, vol, Sharpe, max DD, turnover and equity curve, for IS and OOS | PARTIAL | Sharpe and max DD for both: L92. Equity curve covering IS and OOS: Fig. 2, `results/figures/fig6_v2.png`, L107. Turnover for IS only: L177 "~93× a year". | Annualized return and vol are missing for both periods; OOS turnover is missing. Values are in the table above. |
| 8 | Risk-management and liquidity/capacity sections | MET | §6 L144–162; §7 L164–180. | none |
| 9 | Number of variants tested disclosed | PARTIAL | §8 L184: 44 + 3,342 = 3,386. | Stale. `research/rigor/RESULTS.md` counts 3,410, adding the 24 v2-safe grid variants. The tier-0 grid (`results/tier0/grid.csv`, 864 rows, untracked) and the cost-stress runs aren't counted. Update the total. |
| 10 | Suggested 8-section outline | PARTIAL | §1 Economic foundation, §2 Data and method, §3–4 Results, §6 Risk, §7 Liquidity, §8 Variants and caveats. | No Summary with the headline OOS result at the top. No "Limitations & next steps": §8 never says what you would test with more time or what could break the strategy. The Data section has no survivorship / corporate actions / missing-data paragraph (item 32). |
| 11 | Public repo with README and dependency file; no zip | MET | `README.md`; `requirements.txt` with 9 `==` pins; the repo is public. | none |
| 12 | Repo contains README setup + single command, dependency file, all code, data download scripts | PARTIAL | Setup and `bash reproduce.sh`: README L26–30. Download scripts: `scripts/fetch_polymarket.py`, `fetch_middle.py`, `fetch_reverse.py`. | Unpinned extra packages:<br>• `research/v2/latency/load.py` L19 needs `orjson`.<br>• `src/tracking/early_call.py` L189 needs scikit-learn.<br>• Tracking also needs torch, opencv and av; `hpg/*_setup.sbatch` installs them unpinned.<br>• `docs/deck/build_deck.py` L40 needs python-pptx.<br><br>Tier-0 code that read the OOS is untracked (Fix 7). The live order-book recordings behind the §5 and §7 numbers (`data/live`, gitignored) can't be re-downloaded; say so in the README. |
| 13 | One command reproduces the headline numbers; judges spot-check | PARTIAL | `reproduce.sh` L6–12 regenerates Tables 1–2, the cost stress, the figures, the factor regression and leverage. | • No full run is logged since D9 (`reproduce.log`, 09:47 EDT; `*.log` is gitignored).<br>• The note header L3 gives a different command (`python scripts/v2_burned_oos.py`) from README's `bash reproduce.sh`.<br>• `make_pdf.py` L7 hard-codes a macOS Chrome path, so the last step fails on Linux under `set -e`.<br>• The U2 blind test, v2-safe, latency, liquidity and tracking numbers aren't covered.<br>• `docs/DEVPOST.md` L52 "regenerates every number" overclaims.<br>• Several steps append to `results/oos_peeks.log`; warn judges in the README. |
| 14 | No raw licensed data, API keys or `.env` committed | MET | Pattern scan of all 488 tracked files: no keys (the `0x…` hits are Polymarket condition IDs) and no `.env`, `.pem` or credential files. `.gitignore` excludes `data/` and `.env`. The largest file is the 4.7 MB deck. Committed data are derived outputs of public APIs. | Media:<br>• OpenTTGames-derived clips are CC BY-NC-SA 4.0. They are credited in README L68–70, the demo-reel card (`make_demo_reel.py` L40) and deck slide 4.<br>• No TrackNet broadcast frames are committed (`example_trajectory.png` is a plot).<br>• Add a short LICENSE/NOTICE in `results/tracking/demo/` for the share-alike terms. |
| 15 | All team members listed on Devpost | USER-ACTION | Git shows one author (Ojasva Mishra). `docs/DEVPOST.md` lists no team. | Add every member on Devpost. Devpost shows "Team required", while DP-rules and HG allow solo entries; confirm if solo. |
| 16 | Every source cited in the note | PARTIAL | §8 L189–191 cites Bailey & López de Prado; Harvey, Liu & Zhu; Klaassen & Magnus; TTNet/OpenTTGames; TrackNet; the Polymarket and Kalshi API docs. | Not cited:<br>• Kenneth French Data Library / Fama–French and momentum factors (§4 L110).<br>• ESPN feed and the WTA API (§5 L133).<br>• BlurBall and WASB-SBDT (`src/tracking/README.md` L10–15).<br>• The Polymarket fee/delay documentation.<br>• The core Python libraries.<br><br>Also mark the Hawk-Eye 340 fps / ±3.6 mm figures as *assumed* (`src/hawkeye.py` L11, L27). |
| 17 | Disclose pre-existing components at submission (TERMS 14.2) | PARTIAL | `docs/DEVPOST.md` L31–32 mentions "OpenTTGames with BlurBall weights, TrackNet tennis" in passing. | Add a "Pre-existing components" list to Devpost:<br>• BlurBall weights + WASB-SBDT code (MIT).<br>• TrackNet weights + TennisProject code + TennisCourtDetector (no licence; not redistributed).<br>• OpenTTGames and TrackNet datasets.<br>• Ken French data. |
| 18 | Code can be pushed until 11:00 AM | USER-ACTION | Local main is 1 commit ahead (`1ebb458`). `results/oos_peeks.log` and the paths listed in the snapshot are uncommitted. | Commit and push the final state before **11:00 EDT Sun Oct 4**. Commits after that are not reviewed. |

## B. Method rules

| # | Requirement | Status | Evidence | Gap or fix |
|---|---|---|---|---|
| 19 | Write the edge down before any backtest | MET | `7232986` (Sat 05:50:47 EDT) contains only `HYPOTHESIS.md` and `.gitignore`. The first code commit is `0f1cc89` at 06:15. Hacking began Fri 7:15 PM (live HOME schedule). | `HYPOTHESIS.md` L3 says "Written ~10:15 UTC", but the commit is 09:50 UTC (DEVIATIONS L3 says 09:50). Fix the stamp so judges aren't confused. |
| 20 | Commit the hypothesis before the first backtest | MET | Same as item 19. | none |
| 21 | Template: universe, behaviour, horizon, counterparty, persistence, prediction, falsifier | MET | `HYPOTHESIS.md`: tiers L11–19, persistence L21–25, H1 L27–36 (horizon 10–120 s, "Fails if"), H2–H4 L38–62. NOTE §1 L14–17. | Optional: one template-style sentence in the note. |
| 22 | Any liquid, publicly traded market (chips: equities, ETFs, futures, FX, options, crypto) | USER-ACTION | COURTSIDE trades Polymarket event contracts, with Kalshi as a reference. Prediction markets aren't in the chip list. Devpost can disqualify "data not permitted for its track". NOTE L160–161 itself says Polymarket's international venue restricts US persons. | **Get written organizer confirmation today.** Polymarket is a listed event sponsor on gqhacks.com, which supports asking but is not a ruling. |
| 23 | Sponsor data optional; free public data allowed | MET | Public Polymarket and Kalshi APIs, Ken French, OpenTTGames, TrackNet. HG: "Outside data: allowed". | none |
| 24 | Holdout = last 20% or last 2 years, whichever is shorter | PARTIAL | `src/tape.py` L13, L24–25: last 20% **of matches by count** (2,617 / 13,084), from 2026-08-25 14:15 UTC. | Verified span: 2025-10-08 → 2026-10-03 (360 days). Volume grew over time, so the OOS covers only **38 days = 10.7% of the calendar history**; 20% by time would start 2026-07-23. Disclose the count-based definition and its time share in the note, or justify it. |
| 25 | Set the holdout aside early and don't look | MET | Split coded in `0f1cc89`. Everything frozen at `9d61d1b` (06:32 EDT, D6) before the single v1 OOS open (`oos_peeks.log` L1, 10:42 UTC). | none |
| 26 | Evaluate the holdout once, at the end | PARTIAL | v1 opened once (log L1). The log then has 12 more OOS reads (L2–13), all labelled non-blind; v2 was designed after seeing v1 lose there (NOTE L32–33; HYPOTHESIS_V2 L6–9). | The blind forward test (pending) and the U2 out-of-universe test are the mitigation. Make the forward result the headline OOS once it exists, to limit the "tuning on OOS" cap. |
| 27 | Report the OOS result good or bad; report every peek in the note | PARTIAL | The v1 OOS loss is reported (L65–66); U2 failed and that is reported (L100–105). The note only points to the log (L33). | Say in the note how many times the OOS was read: currently 13 lines, 1 blind and 12 non-blind. `DEVIATIONS.md` D10 L178–179 ("All three") is stale. |
| 28 | Walk-forward tuning inside IS, with a purge gap | PARTIAL | Monthly walk-forward on months strictly before m (`src/fasttier.py` L3, L39–41). The v2 lenses used IS only (D8). | No purge gap is stated anywhere (no "purge" or "embargo" in code or docs). Labels are 30 s markouts or hold-to-resolution within hours; say that leakage across months is negligible, or add a 1-day purge. The sizing and net-cap choices were made on the full IS, not in folds (the rigor-pack PBO covers that). |
| 29 | Lag every signal ≥ 1 bar; trade next; point-in-time | PARTIAL | Causal detection window (D9; HYPOTHESIS_V2 A1). Venue delay + latency in the H1 tests (D1). | **Risk:** v2 fills at the fast tier's own print, the same print that is the signal (L114–115, L186–187). Copying at +3 s loses (Table 1 L51). State plainly that v2 measures the opportunity at tier-0 speed and is not an executable backtest. The universe filter (≥ $5k total match volume, `src/tape.py` L19) is also known only after the match; disclose it. |
| 30 | Cost in bps per trade, justified | PARTIAL | Fees are each match's own `rate·q(1−q)` (L27–28); spreads come from traded side-of-book prints (L25–27); the reasoning is given. | No bps figure anywhere in the note. Add one line, e.g. fee = 10,000·rate·(1−q) bps of notional (250 bps at q = 0.5), and the v2 net edge of 273 bps IS / 114 bps OOS per $ traded. |
| 31 | Show costs doubled; say so if the edge disappears | **MISSING** | Results exist (`results/v2/cost_stress.json`) but are not in the note. The OOS edge turns negative at fees ×2 and at costs ×2. | Add the 3-row table from Fix 2 and one sentence saying the OOS edge does not survive doubled costs. Fix `docs/COMPLIANCE.md` L29. |
| 32 | Survivorship, corporate actions and missing data explained in the note | PARTIAL | The universe is every resolved market from the venue's event list (`docs/COMPLIANCE.md` L28); 2.9% 50/50 settlements are included (NOTE L159). | The note never addresses the three named problems:<br>• Survivorship.<br>• Corporate actions (N/A for binary contracts; say so).<br>• Missing data: verified 0 missing tapes out of 13,084, but 7 tapes hit the data-api 10k-offset cap (`src/polymarket.py` L98–104), so "Full taker tapes" (L25) is overstated for them. |
| 33 | Guard against p-hacking: variant count, plateau, deflated Sharpe | PARTIAL | Variant count L184; plateau L121–122 (onset labelling); luck benchmark "~4.8" L186. | The 4.8 applies to T = 206 days (IS). For the 40-day OOS the rigor pack gives SR* = 11.0 at N = 3,386 and DSR 0.075 (0.48 at N = 44; PSR vs 0 = 0.987). As written, L186 implies OOS 6.7 beats luck. Replace it with the rigor-pack numbers. |
| 34 | Few parameters, simple rules with an economic reason | MET | v2 = 5 rules (L70–74), each with a stated reason. | none |
| 35 | Max DD, skew and worst month next to Sharpe; explain Sharpe > 3 | PARTIAL | Max DD next to Sharpe (L92). Sharpe > 3 explained (L119–122) and benchmarked (L186). | Skew and worst month are missing: IS 0.53 / +$2,543, OOS 0.33 / −$434. |
| 36 | Break down by year or regime | MET | Monthly bars (Fig. 2); months positive (L93); fee/delay regimes (§6 L146–149; `DEVIATIONS.md` D6 L65–66); crowding (L149–150). | none |
| 37 | Originality: cite libraries and research; extend any copied strategy | PARTIAL | All work dates from after hacking began. Third-party models are cited in the `src/*/README.md` files. | Courtsiding and latency arbitrage are known ideas. Add one sentence on what is new: measurement on prediction-market tapes, wallet-level fast-tier persistence, and CV lead time. |
| 38 | AI tools allowed; the team answers for every line | MET | README and `docs/DEVPOST.md` disclose AI coding assistants; DEVPOST mentions verifier agents. | See item 63. |
| 39 | Any language | MET | Python. | none |
| 40 | Check simple explanations; regress on known factors | MET | §4 L110–112: alpha t = 8.5, all betas insignificant, R² 3% (`scripts/factor_regression.py`, `results/v2/factor_regression.json`). | Cite the factor data (item 16). |
| 41 | Size by ADV; capacity in dollars; costs-double | PARTIAL | §7 L166–180: depth, stale depth per point, fast-tier window volume of $0.3–3.1M/month, v2 traded $1.48M on $28k. | Missing:<br>• One dollar capacity figure ("how much capital before the edge erodes").<br>• Position size as a share of volume, e.g. v2 $ vs fast-tier 0–3 s volume or total match volume.<br>• Costs-double (item 31). |
| 42 | Limits, de-risking rules, tail and regime | MET | §6: $1k per order, 100 net shares per match, capital = 3× peak, halve below 0.3¢ and stop at ≤ 0, kill switches, venue-rule and crowding risk. | Small gaps: no gross-exposure cap across concurrent matches; worst-case loss per position isn't stated (only the realized −$206). `docs/COMPLIANCE.md` L35 claims a "daily stop" that §6 doesn't contain. |
| 43 | Keep and report failures | MET | Table 1 (H1, H2, H5); maker exits refuted (L76–79); v1 OOS loss (L65–66); U2 OOS fail (L100–105); `DEVIATIONS.md`. | none |
| 44 | No funded accounts or real trading | MET | README L71–72; no order-placing code is tracked. The untracked `engine/execution/paper.py` blocks the signing libraries. | none |
| 45 | Respect third-party licences and ToS | PARTIAL | Licences are documented in `src/tennis_tracking/README.md` L45–53 and `src/tracking/README.md` L10–21. | • TrackNet code and weights have no licence (all rights reserved); they are used but not redistributed.<br>• ESPN and WTA API terms are unchecked.<br>• Polymarket restricts US persons on its international venue; we only read public data.<br><br>Verify these and mention them in one line. |
| 46 | Judges may re-run against held-out data | N/A | Informational. | See item 13. |

## C. Rubric criteria

| # | Requirement | Status | Evidence | Gap or fix |
|---|---|---|---|---|
| 47 | 5 criteria × 10 = 50 | N/A | Informational. | none |
| 48 | Economic Foundation | MET | §1: explicit counterparty (slower tiers), persistence (physical latency, the venue's 1 s delay), Markov leverage. | The weak spot is that the edge needs tier-0 speed the team doesn't have. Say plainly that this is the thesis. |
| 49 | Innovation | MET | CV ball-tracking lead time + prediction-market microstructure + wallet-level fast-tier persistence. | Add the "what's new" sentence (item 37). |
| 50 | Risk Management Plan | MET | §6. | Close the gaps in item 42 to reach the 7–9 band. |
| 51 | Liquidity & Capital | PARTIAL | §7. | Items 41 and 31: a capacity $ figure, an ADV-style fraction, and costs doubled. |
| 52 | Performance & Analytical Evidence | PARTIAL | Strong IS evidence, the U2 blind test, the rigor pack. | Missing metrics (items 7, 35), costs ×2 (31), forward placeholders (Fix 3). The OOS is weak and burned. |
| 53 | Criterion-5 cap at 4 (code mismatch, lookahead, OOS tuning) | PARTIAL | See Fix 4. | Re-run on a clean clone and diff against the note. Make the same-print framing explicit (29). Headline the blind forward test (26). |
| 54 | Code supports criterion 5; spot-checked | PARTIAL | Same as item 13. | Same as item 13. |
| 55 | Tie-break: Performance, then Economic Foundation | N/A | Informational. | none |
| 56 | No P&L leaderboard; a defensible Sharpe beats a big one | N/A | Informational. The note's tone fits ("positive but not proven", L104–105). | none |
| 57 | Hypothesis up front, fair test, failures, code that runs | PARTIAL | Hypothesis ✓ and failures ✓. | The fair test is only partial (OOS burned, forward pending). Code that runs is unverified since D9. |
| 58 | How sections feed the criteria | N/A | Informational. | none |
| 59 | Judges' decisions final; Massive bonus optional | N/A | COURTSIDE uses no Massive data, so it is not a Massive entry. | none |

## D. Presentation

| # | Requirement | Status | Evidence | Gap or fix |
|---|---|---|---|---|
| 60 | Live 5 min + Q&A, Sun 1:00–3:00 PM, Matthews Suite | USER-ACTION | Confirmed on the live HOME schedule. Deck: `docs/deck/courtside.pptx`, 12 slides (7 main + 5 backup, `build_deck.py` L8). | Rehearse to 5 minutes. When the deck is rebuilt (it won't rebuild until `oos_peeks.log` settles; not edited here), fix: **slide 1 links `github.com/OjasMishra32/courtside`, which returns 404 publicly**, and slide 7 says "3 lines in oos_peeks.log" (it is 13 now). |
| 61 | Sign up for a slot today, 5:00–6:00 PM, Grand Ballroom | USER-ACTION | Live HOME: "05:00 PM Track Check-ins · Grand Ballroom · sign up for a Sunday presentation slot". | Be there today. Ask about items 22 and 62 at the same time. |
| 62 | Presentation format not specified on the track page | USER-ACTION | The live track chunk has no presentation, slide or deck text. | Confirm at the check-in. |
| 63 | Every member can explain the strategy | USER-ACTION | none | Brief every member on v2, D9 and the burned OOS. |

## E. Logistics

| # | Requirement | Status | Evidence | Gap or fix |
|---|---|---|---|---|
| 64 | Deadline Sun Oct 4, 11:00 AM EDT, for both Devpost and the code push | USER-ACTION | Verified live: shell `Date.UTC(2026,9,4,15,0,0)`; Devpost "Oct 4, 2026 @ 11:00am EDT". | The forward test is planned for about 11:30 UTC = **07:30 EDT** (`HYPOTHESIS_V2.md` L31). That leaves about 3.5 h to fill the placeholders, rebuild and check the PDF, commit, push and upload. |
| 65 | The deadline changed today, 10:00 → 11:00 | N/A | Chunk hashes are unchanged since the REQUIREMENTS extraction; "10:00 AM" is gone from the track and shell chunks. | none |
| 66 | Devpost window; winners announced (6:00 PM on Devpost vs 3:40 PM at the ceremony) | N/A | Informational; the two sources conflict. | none |
| 67 | Team size 1–4; in person; one team, one track; rosters locked | USER-ACTION | Not checkable from the repo. | Confirm the roster on Devpost. |
| 68 | Eligibility: 18+, U.S. college enrolment, student ID | USER-ACTION | none | Bring student IDs. |
| 69 | Rule changes announced in Discord and the Hacker Guide; brief not published | USER-ACTION | The track page defers to an unpublished "Participant Brief". | Watch #announcements and ask for the brief. |
| 70 | Code of conduct and Terms | MET | Nothing conflicts. The note flags that courtsiding breaks ticket terms (L160). | none |
| 71 | Back up your own work | USER-ACTION | One unpushed commit; many untracked paths. | Push now. Commit or archive the untracked work you intend to keep. |
| 72 | Prizes | N/A | Informational. | none |
| 73 | Submit even if unfinished | USER-ACTION | none | Submit a complete draft on Devpost well before 11:00 and update it after the forward test. |

## Other inconsistencies found (not numbered requirements)

- `README.md` L16 and L22 cite `results/v2/forward.json` and `results/forward_peeks.log`. Neither exists yet, because the forward test hasn't run.
- `docs/COMPLIANCE.md` overclaims:
  - L29 maps "costs double" to the slippage rows.
  - L31 says skew and worst month are in Table 2; they are not.
  - L35 claims a "daily stop" that §6 doesn't contain.
- `HYPOTHESIS.md` L66 points to `src/split.py`, which doesn't exist; the split is in `src/tape.py`.
- `DEVIATIONS.md` L4–5 says the OOS "has not been opened for any of the analysis below". D7–D10, further down the same file, all come after the OOS was opened. Scope that sentence to D1–D6.
