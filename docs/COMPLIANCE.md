# Systematic Trading track: compliance checklist

Every requirement on the Gator Quant Hacks 2026 Systematic Trading track page, its shared deadline
component, the home page, Devpost, the Hacker Guide and the Participant Terms, and where this repo meets
it. The numbering (1–73) and wording follow `research/compliance/REQUIREMENTS.md`, which quotes each source
verbatim; the live track page was re-checked against it on 2026-10-03 (only the deadline strings had
changed, 10:00 → 11:00 AM).

Note sections (`docs/NOTE.pdf`, LaTeX via tectonic, built by `scripts/build_paper.py`; updated 2026-10-03):
§1 Summary · §2 Economic hypothesis · §3 Data and universe · §4 Methodology · §5 Results · §6 Risk management ·
§7 Liquidity and capacity · §8 Limitations and next steps (pages 1–5) · References (p. 6) · Appendix (Tables A1–A8,
Figures A1–A6). Main floats: Fig. 1 (latency ladder, CV calls), Fig. 2 (fast tier by month, v2 equity curve with
costs doubled), Fig. 3 (signal decay), Table 1 (v2 IS/OOS), Table 2 (CV strategy at the 1 s baseline), Table 3 (failures).
Every number is a key in `results/paper/numbers.json` with its source file and key; the build's acceptance checks
are in `results/paper/checks.json`.

**Status:** Met · Partly met (gap stated) · Team (a person must do it) · Info (nothing to check).

## A. Submission artefacts

| # | Requirement | Status | Where |
|---|---|---|---|
| 1 | Note PDF and public repo link on Devpost; both required | Team | `docs/NOTE.pdf` and the public repo exist; upload the PDF file and paste the repo URL on Devpost |
| 2 | ≤ 5 pages, figures and tables included | Met | `docs/NOTE.pdf`: main text ends on page 5 (`\label{lastmain}`), References from p. 6; `scripts/build_paper.py` fails if `\pageref{lastmain}` > 5 (`results/paper/checks.json::main_pages`) |
| 3 | 11 pt or larger, standard margins | Met | Every text span on pages 1–5 is ≥ 11.0 pt in the PDF, including tables, captions, equations, figure text, header and footer (figures drawn at final size in Source Sans 3 11 pt); Letter, 1 in margins. Checked with pymupdf by `scripts/build_paper.py` (`checks.json::smallest_span_pt`, `margin_violations`) |
| 4 | References and appendix don't count; appendix may go unread | Met | References and the Appendix start after page 5; everything scored is in pages 1–5 (the appendix holds full grids, logs and tallies) |
| 5 | Hypothesis stated before results | Met | §2 (H6 in the track template, with the pre-registration trail) precedes §5; the first P&L float is Fig. 2 on p. 3 |
| 6 | In-sample and OOS reported separately, net of costs | Met | Table 1 (v2) and Table 2 (CV strategy at the 1 s baseline): IS and OOS in separate columns, net of each match's fee and traded spreads |
| 7 | Annualised return, volatility, Sharpe, max DD, turnover, equity curve, for IS and OOS | Met (v2) / Partly met (CV) | v2: Table 1 (annualised return, volatility, Sharpe, max DD, turnover, both periods) and Fig. 2b (equity curve across IS and OOS). CV strategy: Table 2 gives return, volatility, Sharpe, max DD and worst day for both periods; the latency sweep stores no daily path, so its equity curve and turnover are not shown (said in the Table 2 notes; a path would need a new OOS run) |
| 8 | Risk-management and liquidity/capacity sections | Met | §6, §7 (Fig. A1) |
| 9 | Number of variants tested disclosed | Met | Table 3 notes: 4,219 variants tried; Table A4 tallies every family and says which chose nothing |
| 10 | Suggested 8-section outline | Met | §1–§8 follow the blueprint's eight sections in order |
| 11 | Public GitHub repo, README, dependency file; no zip | Met | `README.md`; `requirements.txt` (pinned core); `requirements-extra.txt` (tracking, deck) |
| 12 | README setup + single command; dependency file; all code; data download scripts | Met | README "Reproduce"; `scripts/fetch_polymarket.py` (public APIs, no keys). README states what cannot be re-downloaded (the 2026-10-03 live recordings) |
| 13 | One command reproduces the headline numbers | Partly met | `bash reproduce.sh` regenerates the result files, then `scripts/paper_figures.py` and `scripts/build_paper.py` rebuild every figure, `results/paper/numbers.json` and the PDF (tectonic). The rigor pack, the blind tests, the lenses and HiPerGator tracking are separate commands, listed in the README with their committed outputs |
| 14 | No API keys or licensed raw data committed | Met | `.gitignore` excludes `data/` and `.env`; only public Polymarket/Kalshi data and derived outputs; OpenTTGames-derived clips are CC BY-NC-SA 4.0, credited |
| 15 | All team members listed on Devpost | Team | |
| 16 | Every source cited in the note | Met | §3 "Sources" sentence and References (data APIs, score feeds, Ken French, video, detector weights, vendor latency claims, rules); Table A6 cites the source of every latency |
| 17 | Disclose pre-existing components at submission (Terms 14.2) | Met / Team | README "Pre-existing components"; the same text is in `docs/DEVPOST.md` for the Devpost form |
| 18 | Code can be pushed until 11:00 AM | Team | Final push before Sun Oct 4, 11:00 AM EDT |

## B. Method rules

| # | Requirement | Status | Where |
|---|---|---|---|
| 19 | Write the edge down before any backtest | Met | `HYPOTHESIS.md`, commit `7232986` (2026-10-03 09:50 UTC), contains only the hypothesis; the commit time is authoritative |
| 20 | Commit the hypothesis before the first backtest | Met | Same commit; the first code commit follows it |
| 21 | Template: universe, behaviour, horizon, counterparty, persistence, prediction, falsifier | Met | §2, H6 box (universe, behaviour, horizon, counterparty, persistence, prediction, falsifier) with the commit trail; Table A8 |
| 22 | Any liquid, publicly traded market | Team | Polymarket is a public order book with $2.84B traded in our universe and free tick data (§3). Prediction markets are not among the page's example asset classes; the organizers' written ruling is to be cited here |
| 23 | Sponsor data optional; free public data allowed | Met | Public Polymarket and Kalshi APIs, Ken French, OpenTTGames, TrackNet |
| 24 | Holdout = most recent 20% or 2 years, whichever is shorter | Met (disclosed) | Last 20% of matches by start time (`src/tape.py`): 2,617 matches, 21% of volume; §3. The 11%-of-calendar-time point is in `results/v2/note_metrics.json` |
| 25 | Set the holdout aside early and don't look | Met | Split coded before any result; everything frozen (D6) before the single v1 open (`results/oos_peeks.log` line 1) |
| 26 | Evaluate the holdout once, at the end | Partly met | Opened once, blind, for v1 (Table 3: −$36k). v2 was designed after that, so its held-out numbers are labelled "burned (non-blind)" (§3, Table 1); v2's clean tests are the blind unseen-market test (a fail, Table 3) and the forward test (pending, Table 3) |
| 27 | Report the OOS result good or bad; report every peek in the note | Met | v1's loss, the blind-test fails and the doubled-cost loss are reported (Table 1, Table 3); Table 3 notes count every read of held-out data by class and Table A7 lists every line of `results/oos_peeks.log` at build time |
| 28 | Walk-forward tuning inside IS, with a purge gap | Met (disclosed) | §4 "Validation": monthly walk-forward inside IS; wallets qualify on past months |
| 29 | Lag every signal; trade next; point-in-time data | Met (disclosed) | §4: the window starts at detection (D9); fills at the fast tier's own prints are labelled "the opportunity at their speed, not our execution"; copying 3 s later loses (Fig. 2a) |
| 30 | Cost in bps per trade, justified | Met | §4 "Costs" and Eq. (3): fee = 10,000·r·(1−q) bps; 120 bps IS, 179 bps OOS on v2's trades; spreads paid as traded |
| 31 | Show costs doubled; say so if the edge disappears | Met | Table 1 "Costs stressed" rows (½ and 1 tick, fees ×2, all costs ×2) and Fig. 2b; §5 and the Summary say the OOS edge turns negative when fees double |
| 32 | Survivorship, corporate actions and missing data explained in the note | Met | §3 (volume-filter survivorship checked by the blind unseen-market test, truncated tapes, no-fee matches, 50/50 settlements, block-time stamps) |
| 33 | Guard against p-hacking: variants, plateau, deflated Sharpe | Met | §5 "Sharpe above 3" (D9 bug fix, deflated Sharpe at N = 3,386 for both periods); Table A4 variant tally |
| 34 | Few parameters, simple rules with an economic reason | Met | §4: the v2 rules (detector, past-month qualification, sizing, caps, hold), each with its reason |
| 35 | Max DD, skew and worst month next to Sharpe; explain Sharpe > 3 | Met | Table 1 rows (skew and worst month next to Sharpe and max DD); §5 "Sharpe above 3" for v2 and the CV simulation |
| 36 | Break results down by year or regime | Met | Fig. 2a (by month), §2 (fee/delay regimes), Table 1 (months positive), Fig. A3 (regimes and months) |
| 37 | Cite libraries and research; say what is new | Met | §2 last sentences ("new here"); References |
| 38 | AI tools allowed; the team answers for every line | Team | Disclosed in README; every member must be able to explain the code and note |
| 39 | Any language | Info | Python |
| 40 | Check simple explanations; regress on known factors | Met | §6 "Largest risks": IS-only Fama–French + momentum α t = 8.48, max factor |t| 1.36, R² 3.3%; Table A3 (three specifications, the committed file flagged) |
| 41 | Size by ADV; capacity in dollars; costs double | Met | §7: $7,182 a day, 0.07% of match volume; OOS edge survives only up to 1× size ($22,754 capital); stale depth; break-even fee before and after fixed costs; Fig. A1; doubled costs in Table 1 |
| 42 | Limits, de-risking rules, tail and regime | Met | §6: limits, de-risking rules set in advance, code-level kill switches (`engine/risk/limits.py`), venue-rule, crowding and tail risk |
| 43 | Keep and report failures | Met | Table 3 (every failed or pending test) and the Summary box "What failed"; `DEVIATIONS.md` |
| 44 | No funded accounts or real trading | Met | Read-only code; the engine is paper-only |
| 45 | Respect third-party licences and terms | Partly met | README "Data, sources and licences": TrackNet code and weights carry no licence and are used unmodified, not redistributed; ESPN/WTA terms were not reviewed (only derived timings committed) |
| 46 | Judges may re-run against held-out data | Info | `scripts/forward_test.py --start ... --end ...` runs v2 on any window |

## C. Rubric

| # | Requirement | Status | Where |
|---|---|---|---|
| 47 | Five criteria × 10 = 50 | Info | |
| 48 | Economic Foundation | — | §2 (counterparty, persistence, regime evidence), Fig. 1a, Fig. 2a |
| 49 | Innovation | — | §2 "new here"; §4 CV strategy; Fig. 1, Fig. 3 |
| 50 | Risk Management Plan | — | §6 |
| 51 | Liquidity & Capital | — | §7, Fig. A1, Table 1 cost rows |
| 52 | Performance & Analytical Evidence | — | §5, Tables 1–3, Figs. 2–3 |
| 53 | Criterion-5 cap (code mismatch, lookahead, OOS tuning) | Partly met | Same-print fills labelled in §4 and Table 1; burned window labelled and every look listed (Table 3 notes, Table A7); clean tests are blind. Team: re-run `reproduce.sh` on a clean clone and diff `results/paper/numbers.json` before submitting |
| 54 | Code supports criterion 5 and is spot-checked | Partly met | As item 13 |
| 55 | Tie-break: Performance, then Economic Foundation | Info | |
| 56 | No P&L leaderboard | Info | |
| 57 | Hypothesis up front, fair test, failures, code that runs | Partly met | Hypothesis, failures and code: yes. Fair test: v2's held-out window is burned; the forward test is the blind one (pending until it runs) |
| 58 | How sections feed the criteria | Met | The paper follows the blueprint outline (§1–§8) |
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
| 70 | Code of conduct and Terms | Met | Nothing conflicts; §6 flags courtsiding's ticket-terms issue |
| 71 | Back up your own work | Team | Push to the public repo |
| 72 | Prizes | Info | |
| 73 | Submit even if unfinished | Team | |

## Extra integrity measures (beyond the brief)
- Adversarial verifier reports for every optimisation lens and for v2 (`research/v2/*/verify_*`, `research/v2/verify_v2/`).
- A blind test on 11,307 never-examined markets, pre-registered before any result (`research/v2/expand/PREREG.md`).
- A blind forward test on matches played after the pre-registration (`HYPOTHESIS_V2.md`, `scripts/forward_test.py`, logged in `results/forward_peeks.log` when run).
- A rigor pack on the existing results: deflated Sharpe, PBO, block bootstrap, minimum track record (`research/rigor/RESULTS.md`).
- The code is read-only and never places an order.
