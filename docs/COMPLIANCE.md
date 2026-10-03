# Systematic Trading track: compliance checklist

Every requirement on the Gator Quant Hacks 2026 Systematic Trading track page, its shared deadline
component, the home page, Devpost, the Hacker Guide and the Participant Terms, and where this repo meets
it. The numbering (1–73) and wording follow `research/compliance/REQUIREMENTS.md`, which quotes each source
verbatim; the live track page was re-checked against it on 2026-10-03 (only the deadline strings had
changed, 10:00 → 11:00 AM).

Note sections: Summary · §1 Economic hypothesis · §2 Data and universe · §3 Methodology · §4 Results ·
§5 Risk management · §6 Liquidity and capacity · §7 Limitations and next steps · References.

**Status:** Met · Partly met (gap stated) · Team (a person must do it) · Info (nothing to check).

## A. Submission artefacts

| # | Requirement | Status | Where |
|---|---|---|---|
| 1 | Note PDF and public repo link on Devpost; both required | Team | `docs/NOTE.pdf` and the public repo exist; upload the PDF file and paste the repo URL on Devpost |
| 2 | ≤ 5 pages, figures and tables included | Met | `docs/NOTE.pdf`: 5 pages including references; check with the command in `scripts/make_pdf.py` |
| 3 | 11 pt or larger, standard margins | Met | `scripts/make_pdf.py`: every text style 11.1 pt (body, tables, captions, code), Letter, 1 in margins. Text inside figure images is excepted |
| 4 | References and appendix don't count; appendix may go unread | Met | No appendix; references fit inside the 5 pages; every material claim is in the body |
| 5 | Hypothesis stated before results | Met | §1 (H6 in the track's template) precedes §4; pre-registration trail in §1 |
| 6 | In-sample and OOS reported separately, net of costs | Met | Table 1 (H1–H6, v1) and Table 2 (v2), separate columns, net of each match's fee and traded spreads |
| 7 | Annualised return, volatility, Sharpe, max DD, turnover, equity curve, for IS and OOS | Met | Table 2 (all five metrics, both periods) and Fig. 1 (equity curve across both). Derived rows: `scripts/note_metrics.py` → `results/v2/note_metrics.json` |
| 8 | Risk-management and liquidity/capacity sections | Met | §5, §6 |
| 9 | Number of variants tested disclosed | Met | §7: 3,410 configurations (44 + 3,342 + 24), plus 432 tier-0 counterfactual scenarios and 4 cost-stress cases |
| 10 | Suggested 8-section outline | Met | Summary, §1–§7 follow the blueprint's eight sections in order |
| 11 | Public GitHub repo, README, dependency file; no zip | Met | `README.md`; `requirements.txt` (pinned core); `requirements-extra.txt` (tracking, deck) |
| 12 | README setup + single command; dependency file; all code; data download scripts | Met | README "Reproduce"; `scripts/fetch_polymarket.py` (public APIs, no keys). README states what cannot be re-downloaded (the 2026-10-03 live recordings) |
| 13 | One command reproduces the headline numbers | Partly met | `bash reproduce.sh` regenerates Tables 1–2, the derived metrics and Fig. 1. The rigor pack, the blind tests, the lenses and HiPerGator tracking are separate commands, listed in the README with their committed outputs |
| 14 | No API keys or licensed raw data committed | Met | `.gitignore` excludes `data/` and `.env`; only public Polymarket/Kalshi data and derived outputs; OpenTTGames-derived clips are CC BY-NC-SA 4.0, credited |
| 15 | All team members listed on Devpost | Team | |
| 16 | Every source cited in the note | Met | §2 "Sources" and References (data APIs, score feeds, Ken French, videos, detector weights, methods, libraries) |
| 17 | Disclose pre-existing components at submission (Terms 14.2) | Met / Team | README "Pre-existing components"; the same text is in `docs/DEVPOST.md` for the Devpost form |
| 18 | Code can be pushed until 11:00 AM | Team | Final push before Sun Oct 4, 11:00 AM EDT |

## B. Method rules

| # | Requirement | Status | Where |
|---|---|---|---|
| 19 | Write the edge down before any backtest | Met | `HYPOTHESIS.md`, commit `7232986` (2026-10-03 09:50 UTC), contains only the hypothesis; the commit time is authoritative |
| 20 | Commit the hypothesis before the first backtest | Met | Same commit; the first code commit follows it |
| 21 | Template: universe, behaviour, horizon, counterparty, persistence, prediction, falsifier | Met | §1, H6 block quote |
| 22 | Any liquid, publicly traded market | Team | Polymarket is a public order book with $2.84B traded in our universe and free tick data (§2). Prediction markets are not among the page's example asset classes; the organizers' written ruling is to be cited here |
| 23 | Sponsor data optional; free public data allowed | Met | Public Polymarket and Kalshi APIs, Ken French, OpenTTGames, TrackNet |
| 24 | Holdout = most recent 20% or 2 years, whichever is shorter | Met (disclosed) | Last 20% of matches by start time (`src/tape.py`): 2,617 matches, 21% of volume. §2 states that this covers 11% of the calendar span and that a 20%-of-time split would start on Jul 23 |
| 25 | Set the holdout aside early and don't look | Met | Split coded before any result; everything frozen (D6) before the single v1 open (`results/oos_peeks.log` line 1) |
| 26 | Evaluate the holdout once, at the end | Partly met | Opened once, blind, for v1 (reported: −$36k). v2 was designed after that, so §4 labels its held-out numbers "burned, non-blind"; v2's clean tests are the pre-registered blind test on unseen markets (a fail, reported) and the forward test |
| 27 | Report the OOS result good or bad; report every peek in the note | Met | v1's loss, the blind-test fail and the doubled-cost loss are reported; §4 "Every look at held-out data" itemises all 15 log lines |
| 28 | Walk-forward tuning inside IS, with a purge gap | Met (disclosed) | §3 "Validation": monthly walk-forward; labels are 30 s markouts, so overlap is ≤ 30 s and no further purge was used; sizing and net cap chosen on the whole IS, covered by PBO (§4) |
| 29 | Lag every signal; trade next; point-in-time data | Met (disclosed) | §3 "Execution": the window starts at detection (D9); wallets qualify on past months; v2's fills at the fast tier's own prints are stated as the opportunity at their speed, not our execution; the lagged copy loses (Table 1). The ex-post $5k volume filter is disclosed in §2 |
| 30 | Cost in bps per trade, justified | Met | §3 "Costs": fee = 10,000·rate·(1−q) bps; 120 bps in sample, 179 bps out of sample on v2's trades; half-spread ≈ 95–99 bps; source: published fees and traded prices |
| 31 | Show costs doubled; say so if the edge disappears | Met | Table 2 rows "fees ×2" and "all costs ×2"; §4 "Costs doubled: the out-of-sample edge disappears"; Summary |
| 32 | Survivorship, corporate actions and missing data explained in the note | Met | §2 "Survivorship, corporate actions, missing data" |
| 33 | Guard against p-hacking: variants, plateau, deflated Sharpe | Met | §4 "Sharpe above 3" (plateau, PBO, DSR at N = 3,386 for both periods); §7 variant count |
| 34 | Few parameters, simple rules with an economic reason | Met | §3: five v2 rules, each with its reason |
| 35 | Max DD, skew and worst month next to Sharpe; explain Sharpe > 3 | Met | Table 2 rows; §4 "Sharpe above 3" |
| 36 | Break results down by year or regime | Met | Fig. 1 monthly bars; months positive (Table 2); fee/delay regimes (§1, §5) |
| 37 | Cite libraries and research; say what is new | Met | §1 "What is new"; References |
| 38 | AI tools allowed; the team answers for every line | Team | Disclosed in README; every member must be able to explain the code and note |
| 39 | Any language | Info | Python |
| 40 | Check simple explanations; regress on known factors | Met | §5 "Factor exposure": alpha t = 8.5, all betas insignificant, R² = 3% (`scripts/factor_regression.py`) |
| 41 | Size by ADV; capacity in dollars; costs double | Met | §6: v2 is 0.07% of the same matches' volume; capacity frontier, about $100k; doubled costs in Table 2 |
| 42 | Limits, de-risking rules, tail and regime | Met | §5: backtested limits vs deployment rules, daily stop and kill switches (`engine/risk/limits.py`), tail statistics, venue regimes, concentration; untested caps are named |
| 43 | Keep and report failures | Met | Table 1; §7 "What did not work"; `DEVIATIONS.md` |
| 44 | No funded accounts or real trading | Met | Read-only code; the engine is paper-only |
| 45 | Respect third-party licences and terms | Partly met | README "Data, sources and licences": TrackNet code and weights carry no licence and are used unmodified, not redistributed; ESPN/WTA terms were not reviewed (only derived timings committed) |
| 46 | Judges may re-run against held-out data | Info | `scripts/forward_test.py --start ... --end ...` runs v2 on any window |

## C. Rubric

| # | Requirement | Status | Where |
|---|---|---|---|
| 47 | Five criteria × 10 = 50 | Info | |
| 48 | Economic Foundation | — | §1 (counterparty, persistence, regime evidence), Table 1 |
| 49 | Innovation | — | §1 "What is new"; §6 latency and ball-tracking measurements |
| 50 | Risk Management Plan | — | §5 |
| 51 | Liquidity & Capital | — | §6, Table 2 cost rows |
| 52 | Performance & Analytical Evidence | — | §4 |
| 53 | Criterion-5 cap (code mismatch, lookahead, OOS tuning) | Partly met | Same-print fills framed in §3; burned window labelled and every look listed (§4); clean tests are blind. Team: re-run `reproduce.sh` on a clean clone and diff against the note before submitting |
| 54 | Code supports criterion 5 and is spot-checked | Partly met | As item 13 |
| 55 | Tie-break: Performance, then Economic Foundation | Info | |
| 56 | No P&L leaderboard | Info | |
| 57 | Hypothesis up front, fair test, failures, code that runs | Partly met | Hypothesis, failures and code: yes. Fair test: v2's held-out window is burned; the forward test is the blind one |
| 58 | How sections feed the criteria | Met | Note follows the blueprint outline |
| 59 | Judges' decisions final; Massive bonus optional | Info | Not a Massive entry |

## D. Presentation and E. Logistics

| # | Requirement | Status | Where |
|---|---|---|---|
| 60 | Live 5-minute talk + Q&A, Sun 1:00–3:00 PM, Matthews Suite | Team | `docs/deck/courtside.pptx` |
| 61 | Sign up for a slot Sat 5:00–6:00 PM, Grand Ballroom | Team | |
| 62 | Presentation format not specified on the track page | Team | Confirm at check-in |
| 63 | Every member can explain the strategy | Team | |
| 64 | Deadline Sun Oct 4, 11:00 AM EDT, Devpost and final push | Team | |
| 65 | Deadline changed 10:00 → 11:00 AM | Info | |
| 66 | Devpost window; winners announced | Info | |
| 67 | Team size 1–4, in person, one track, rosters locked | Team | |
| 68 | Eligibility: 18+, U.S. college, student ID | Team | |
| 69 | Rule changes in Discord and the Hacker Guide; brief not published | Team | |
| 70 | Code of conduct and Terms | Met | Nothing conflicts; the note flags courtsiding's ticket-terms issue (§5) |
| 71 | Back up your own work | Team | Push to the public repo |
| 72 | Prizes | Info | |
| 73 | Submit even if unfinished | Team | |

## Extra integrity measures (beyond the brief)
- Adversarial verifier reports for every optimisation lens and for v2 (`research/v2/*/verify_*`, `research/v2/verify_v2/`).
- A blind test on 11,307 never-examined markets, pre-registered before any result (`research/v2/expand/PREREG.md`).
- A blind forward test on matches played after the pre-registration (`HYPOTHESIS_V2.md`, `scripts/forward_test.py`, logged in `results/forward_peeks.log` when run).
- A rigor pack on the existing results: deflated Sharpe, PBO, block bootstrap, minimum track record (`research/rigor/RESULTS.md`).
- The code is read-only and never places an order.
