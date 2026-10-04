# Systematic Trading track: compliance checklist

Every requirement on the Gator Quant Hacks 2026 Systematic Trading track page, its shared deadline
component, the home page, Devpost, the Hacker Guide and the Participant Terms, and where this repo meets
it. The numbering (1–73) and wording follow `research/compliance/REQUIREMENTS.md`, which quotes each source
verbatim; the live track page was re-checked against it on 2026-10-03 (only the deadline strings had
changed, 10:00 → 11:00 AM).

Note sections (`docs/NOTE.pdf`, LaTeX via tectonic, built by `scripts/build_paper.py`; final version 2026-10-04,
figures from `results/paper/v2` drawn by `scripts/paper_figures_v2.py`): §1 Summary · §2 Economic hypothesis · §3 Data and
universe · §4 Methodology · §5 Results · §6 Risk management · §7 Liquidity and capacity · §8 Limitations and next steps
(pages 1–5) · References (pp. 6–7) · Appendix (pp. 8–25: Figures A1–A10, Tables A1–A10, Calculations C1–C13).
Main floats: Table 1 (headline metrics: A, v2 and v2-safe Sharpe with bootstrap CI, deflated Sharpe, ¢/share,
return/vol, max DD/worst month, turnover/skew, IS and OOS; B, the CV strategy at the 0.5 / 1 / 3 s feed-latency
scenarios, $/day, Sharpe and ¢/share with CI, pre-registered reading first, post hoc second, break-even, per-point,
no-early-call and live-engine rows), Table 2 (best version of each component and how it was chosen), Fig. 1 (fast tier
by month; v2 equity curve with costs doubled), Fig. 2 ($/day against feed delay, IS and OOS, with 0.5 / 1 / 3 s lines and
the licensed-video source band), Table 3 (robustness: costs, blind and ex-ante tests, rigor; forward test and live
session not run), Fig. 3 (frame to executable order against the 3 s bar). Appendix: Fig. A1 latency ladder and early
calls (live causal engine vs the offline evaluation with a look-ahead feature), Fig. A2 CV still, Table A1 everything
we tested, Calculations (every formula with a worked example), Fig. A3 capacity and fixed costs, Fig. A4 CV capacity
in $, Fig. A5 sweep by stamp lag, Tables A2–A3 sweep ($/day, Sharpe), A4 ex-ante selective replay, Fig. A6 decay and
the live-book replay, Fig. A7 regimes and months, Fig. A8 every test on one axis, Fig. A9 concentration, Fig. A10 spin
simulation, Tables A5 factor regressions, A6 variant tally, A7 fixed costs, A8 latency ladder sources, A9 every read of
held-out data, A10 pre-registration and deviation trail.
Every number is a key in `results/paper/numbers.json` with its source file and key; the build's acceptance checks
are in `results/paper/checks.json`.

**Status:** Met · Partly met (gap stated) · Team (a person must do it) · Info (nothing to check).

## A. Submission artefacts

| # | Requirement | Status | Where |
|---|---|---|---|
| 1 | Note PDF and public repo link on Devpost; both required | Team | `docs/NOTE.pdf` and the public repo exist; upload the PDF file and paste the repo URL on Devpost |
| 2 | ≤ 5 pages, figures and tables included | Met | `docs/NOTE.pdf`: main text ends on page 5 (`\label{lastmain}`), References from p. 6; `scripts/build_paper.py` fails if `\pageref{lastmain}` > 5 (`results/paper/checks.json::main_pages`) |
| 3 | 11 pt or larger, standard margins | Met | Every text span on pages 1–5 is ≥ 11.0 pt in the PDF, including tables, captions, equations, figure text, header and footer (figures drawn at final size in Source Sans 3 at 11–12 pt); Letter, 1 in margins. Checked by `scripts/build_paper.py` with pymupdf (`results/paper/checks.json`: smallest main-text span 11.0 pt, no span in the margins) |
| 4 | References and appendix don't count; appendix may go unread | Met | References and the Appendix start after page 5; everything scored is in pages 1–5 (the appendix holds full grids, logs and tallies) |
| 5 | Hypothesis stated before results | Met | §2 (H6 in the track template, with the pre-registration trail) precedes §5; the first P&L figure is Fig. 1 on p. 4 |
| 6 | In-sample and OOS reported separately, net of costs | Met | Table 1: IS and OOS in separate columns for v2, v2-safe and the CV strategy at each feed-latency scenario, net of each match's fee and traded spreads |
| 7 | Annualised return, volatility, Sharpe, max DD, turnover, equity curve, for IS and OOS | Met (v2) / Partly met (CV) | v2: Table 1A (annualised return, volatility, Sharpe with CI, deflated Sharpe, max DD, worst month, turnover, skew, both periods) and Fig. 1b (equity curve across IS and OOS). CV strategy: Table 1B gives $/day, Sharpe and ¢/share with CI at 0.5, 1 and 3 s for both periods and both stamp-lag readings; the latency sweep stores no daily path, so its equity curve is not shown (a path would need a new OOS run) |
| 8 | Risk-management and liquidity/capacity sections | Met | §6, §7 (Fig. 3, Fig. A4) |
| 9 | Number of variants tested disclosed | Met | Table 3 notes: 4,219 variants tried; Table A6 tallies every family and says which chose nothing, including the two post hoc presentation choices |
| 10 | Suggested 8-section outline | Met | §1–§8 follow the blueprint's eight sections in order |
| 11 | Public GitHub repo, README, dependency file; no zip | Met | `README.md`; `requirements.txt` (pinned core); `requirements-extra.txt` (tracking, deck) |
| 12 | README setup + single command; dependency file; all code; data download scripts | Met | README "Reproduce"; `scripts/fetch_polymarket.py` (public APIs, no keys). README states what cannot be re-downloaded (the 2026-10-03 live recordings) |
| 13 | One command reproduces the headline numbers | Partly met | `bash reproduce.sh` regenerates the result files, then `scripts/build_paper.py` redraws every figure (`scripts/paper_figures_v2.py`), writes `results/paper/numbers.json` and compiles the PDF (tectonic). The rigor pack, the blind tests, the lenses and HiPerGator tracking are separate commands, listed in the README with their committed outputs |
| 14 | No API keys or licensed raw data committed | Met | `.gitignore` excludes `data/` and `.env`; only public Polymarket/Kalshi data and derived outputs; OpenTTGames-derived clips are CC BY-NC-SA 4.0, credited |
| 15 | All team members listed on Devpost | Team | |
| 16 | Every source cited in the note | Met | §3 sources sentence and References (data APIs, score feeds, Ken French, video, detector weights, vendor latency claims, rules); Table A8 cites the source of every latency |
| 17 | Disclose pre-existing components at submission (Terms 14.2) | Met / Team | README "Pre-existing components"; the same text is in `docs/DEVPOST.md` for the Devpost form |
| 18 | Code can be pushed until 11:00 AM | Team | Final push before Sun Oct 4, 11:00 AM EDT |

## B. Method rules

| # | Requirement | Status | Where |
|---|---|---|---|
| 19 | Write the edge down before any backtest | Met | `HYPOTHESIS.md`, commit `7232986` (2026-10-03 09:50 UTC), contains only the hypothesis; the commit time is authoritative |
| 20 | Commit the hypothesis before the first backtest | Met | Same commit; the first code commit follows it |
| 21 | Template: universe, behaviour, horizon, counterparty, persistence, prediction, falsifier | Met | §2, H6 box (universe, behaviour, horizon, counterparty, persistence, prediction, falsifier) with the commit trail; Table A10 |
| 22 | Any liquid, publicly traded market | Team | Polymarket is a public order book with $2.84B traded in our universe and free tick data (§3). Prediction markets are not among the page's example asset classes; the organizers' written ruling is to be cited here |
| 23 | Sponsor data optional; free public data allowed | Met | Public Polymarket and Kalshi APIs, Ken French, OpenTTGames, TrackNet |
| 24 | Holdout = most recent 20% or 2 years, whichever is shorter | Met (disclosed) | Last 20% of matches by start time (`src/tape.py`): 2,617 matches, 21% of volume; §3. The 11%-of-calendar-time point is in `results/v2/note_metrics.json` |
| 25 | Set the holdout aside early and don't look | Met | Split coded before any result; everything frozen (D6) before the single v1 open (`results/oos_peeks.log` line 1) |
| 26 | Evaluate the holdout once, at the end | Partly met | Opened once, blind, for v1 (Table 3: −$36,056). v2 and the CV simulation were designed after that, so their held-out numbers are labelled "burned (non-blind)" (abstract, §3, Table 1); v2's clean test is the blind unseen-market test (a fail, Table 3); the forward test was not run (submitted before the forward window closed; `HYPOTHESIS_V2.md` A3, Table 3); the CV simulation's clean test is the blind test of its frozen v3 rule (a fail, Table 3) |
| 27 | Report the OOS result good or bad; report every peek in the note | Met | v1's loss, the blind-test fails and the doubled-cost loss are reported (Tables 1 and 3); Table 3 notes count the reads of held-out data (77) and Table A9 lists every line of `results/oos_peeks.log` at build time, a line logged after its run in bold |
| 28 | Walk-forward tuning inside IS, with a purge gap | Met (disclosed) | §4 "Validation": monthly walk-forward inside IS; wallets qualify on past months |
| 29 | Lag every signal; trade next; point-in-time data | Met (disclosed) | §4 (wallets qualify on past months only; fills at the fast tier's own prints are labelled "the opportunity at their speed, not our execution"); §5 (the onset look-ahead found and fixed, D9); copying 3 s later loses (Fig. 1a) |
| 30 | Cost in bps per trade, justified | Met | §4 "Costs": fee = r·q·(1−q) per share = 10,000·r·(1−q) bps of notional, r = 5%; worked example in the appendix (Calculations C9); spreads paid as traded |
| 31 | Show costs doubled; say so if the edge disappears | Met | Table 3 rows (½ and 1 tick worse entry, fees ×2, all costs ×2) and Fig. 1b; §5 and the Summary say the OOS edge turns negative when fees double |
| 32 | Survivorship, corporate actions and missing data explained in the note | Met | §3 (volume-filter survivorship checked by the blind unseen-market test, truncated tapes, no-fee matches, 50/50 settlements, block-time stamps) |
| 33 | Guard against p-hacking: variants, plateau, deflated Sharpe | Met | §5 "Sharpe above 3" (D9 bug fix; deflated Sharpe at N = 3,386, Table 1); Table A6 variant tally; PBO and the bootstrap in Table 3; formulas and worked examples in the appendix (Calculations C4–C7) |
| 34 | Few parameters, simple rules with an economic reason | Met | §4: the v2 rules (detector, past-month qualification, sizing, caps, hold), each with its reason |
| 35 | Max DD, skew and worst month next to Sharpe; explain Sharpe > 3 | Met | Table 1 rows (max DD, worst month, skew next to Sharpe and deflated Sharpe); §5 "Sharpe above 3"; Table 1 notes: the CV Sharpe ranks a simulation over trades selected on outcomes |
| 36 | Break results down by year or regime | Met | Fig. 1a (by month), §2 (fee/delay regimes), Fig. A7 (regimes and months) |
| 37 | Cite libraries and research; say what is new | Met | §2 last sentences ("new here"); References |
| 38 | AI tools allowed; the team answers for every line | Team | Disclosed in README; every member must be able to explain the code and note |
| 39 | Any language | Info | Python |
| 40 | Check simple explanations; regress on known factors | Met | §6 "Tail, venue, legal": IS-only Fama–French + momentum α t = 8.48, max factor |t| 1.36; Table A5 (three specifications, the committed file flagged); Calculations C8 |
| 41 | Size by ADV; capacity in dollars; costs double | Met | §7: v2 trades $7,182 a day, 0.07% of match volume, OOS edge survives only up to 1× size ($22,754 capital); the CV book has no capacity at the pre-registered lag; at the post hoc lag its Sharpe halves at $40,000 (OOS) / $73,000 (IS) of capital and it trades 0.22% of in-play volume (9% of the fast tier's 0–3 s volume); fixed-cost break-even capital and the most it can pay for data; Fig. A4 (Sharpe and $/day against capital), Fig. A3; doubled costs in Table 3 |
| 42 | Limits, de-risking rules, tail and regime | Met | §6: limits and kill switches in code (`engine/risk/limits.py`) with the most one match can lose; de-risking rules set in advance; CV model risk (wrong calls, confidence gate, phantom calls and the rally gate); tail, settlement (UMA), US access, legal; factors |
| 43 | Keep and report failures | Met | Table 3 (every blind or ex-ante test, all failed; forward test and live session not run) and the Summary box "What failed"; Table A4 (ex-ante replay); Table A1 (everything we tested); `DEVIATIONS.md` and `research/v2/tier0/DEVIATIONS.md` (rule changes after a look, counted in the Table 3 notes) |
| 44 | No funded accounts or real trading | Met | Read-only code; the engine is paper-only |
| 45 | Respect third-party licences and terms | Partly met | README "Data, sources and licences": TrackNet code and weights carry no licence and are used unmodified, not redistributed; ESPN/WTA terms were not reviewed (only derived timings committed) |
| 46 | Judges may re-run against held-out data | Info | `scripts/forward_test.py --start ... --end ...` runs v2 on any window |

## C. Rubric

| # | Requirement | Status | Where |
|---|---|---|---|
| 47 | Five criteria × 10 = 50 | Info | |
| 48 | Economic Foundation | — | §2 (Markov leverage Eq. 1 with a worked example in Calculations C10, information tiers, counterparty = the maker with a stale quote, persistence and the measured decay), H6 box, Fig. 1a, Fig. A1a |
| 49 | Innovation | — | §2 "new here"; §4 the latency budget (Eq. 2, worked example in Calculations C11) and the measured pipeline (Fig. 3); Table 2 (best version of each component); Fig. 2 and Table 1B (value of each second of feed delay at 0.5 / 1 / 3 s) |
| 50 | Risk Management Plan | — | §6 (limits in code, de-risking rules, CV model risk, tail/venue/legal); Table 1 (drawdown, worst month, skew) |
| 51 | Liquidity & Capital | — | §7 (v2 and CV capacity in dollars, fixed-cost business case, the stamp lag needed for the cheapest data stack), Fig. A4, Fig. A3, Table 3 cost rows |
| 52 | Performance & Analytical Evidence | — | §5, Tables 1–3, Figs. 1–3; appendix Table A1 (everything we tested), Calculations, Tables A2–A4, Figs. A1–A10 |
| 53 | Criterion-5 cap (code mismatch, lookahead, OOS tuning) | Partly met | Same-print fills labelled in §4 and Table 1; the CV trade set is labelled "selected on outcomes, not ex ante" (Table 1 notes, §4) and the ex-ante tests are reported (Table 3, Table A4); the pre-registered stamp-lag reading is shown first and the post hoc estimate carries its interval and premise (Table 1, §4); the offline call table is labelled as an offline evaluation with a look-ahead feature and the live causal engine leads (Table 2, Fig. A1b); burned window labelled and every look listed (Table 3 notes, Table A9); the two post hoc presentation choices are counted as trials (Table A6). Team: re-run `reproduce.sh` on a clean clone and diff `results/paper/numbers.json` before submitting |
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
