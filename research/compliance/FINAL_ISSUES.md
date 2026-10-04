# Final issues for the main session (paper and video only)

Written 2026-10-04 ~04:15 UTC by the docs/deck integration pass, against the paper at `e62957a`. Everything that could be fixed outside the paper
(`docs/NOTE.pdf`, `docs/paper/**`) and the final video (`results/viz/courtside_60.mp4`) was fixed and committed; the
items below need an edit to one of those two, which this pass may not make. Each item: file, location, old -> new.
Numbers are the paper's (`results/paper/numbers.json`). `bash run.sh redteam` lists items V1-V3 as KNOWN.

## Video (`results/viz/courtside_60.mp4`, built by `scripts/make_video_60.py`)

**V1 (P0). The profit segment shows "$pendingk–$pendingk" (about 73-86 s).**
- Cause: `scripts/make_video_60.py:1621-1628` and `:2726-2732` read `results/capacity/capacity.json`
  `growth['lagcal|cov10|IS']` / `['lagcal|cov10|burned_OOS']` / `['prereg|cov10|…']`, which are null, so
  `cap_lc_is`, `cap_lc_oos`, `cap_pr_is` and `cap_pr_oos` are None (manifest `values.cap_*`, `pending: true`).
- Key the paper uses: `answers.cv.lagcal|phi0.5|cov10|g1|IS.at_half_sharpe.capital_usd` = 73,288 and
  `answers.cv.lagcal|phi0.5|cov10|g1|burned_OOS.at_half_sharpe.capital_usd` = 40,245 (numbers.json `capcv.half.is`
  $73,000, `capcv.half.oos` $40,000). Pre-registered: no capacity (Sharpe 2.7 / 0.8 at the smallest size).
- On screen, profit rail (`make_video_60.py:3941-3943`):
  old `"$pendingk–$pendingk"` / `"capital where Sharpe halves (post-hoc); $pendingk–$pendingk pre-registered"`
  -> new `"$40k–$73k"` / `"capital where Sharpe halves (post hoc, held out – in sample); none pre-registered"`.
- Also the stats-card variant at `make_video_60.py:1631-1636` (old `"pre-registered: $…k–$…k"` -> new
  `"pre-registered: none"`; and old `"of capital, calibrated"` -> new `"of capital, post hoc"`).
- Only this one segment needs re-rendering; the deck, README and Q&A (QA_PREP §7) give the paper's numbers meanwhile.

**V2. The video never says the CV trade set is "selected on outcomes, not ex ante"** (redteam check 3, KNOWN).
- Location: speed or profit segment (55-86 s), the label line.
- old: `"simulated 1 s licensed-feed baseline"` -> new: `"simulated 1 s licensed-feed baseline · trades selected on
  outcomes, not ex ante"`.

**V3. The video does not show the per-point reading of the same clocks** (redteam check 5, KNOWN).
- Paper: post hoc read per point loses −$17 a day at 1 s (numbers.json `cv.stc.oos.usd` / `pp.pre.oos.usd`).
- Location: speed segment (55.4-63.4 s), under "every second costs money". Add: `"read per point: −$17 a day at 1 s"`.

**V4. "3,410 variants counted"** (end of the test segment, pill at `make_video_60.py:3856`).
- Paper: 4,219 variants in all; 3,386 trials in the deflated Sharpe; 3,410 = the DSR set plus the v2-safe grid
  (`rigor.json::psr_dsr.N.all_plus_v2safe_grid`).
- old `"3,410 variants counted"` -> new `"3,410 strategy variants (4,219 in all)"`. Reconciled meanwhile in the deck
  (slide 8), README (Rigour row), Devpost and QA_PREP §7.

**V5. "blind tests: 2 pass · 4 fail"** (pill at `make_video_60.py:3855`).
- Paper: every blind test of a tradable book failed. The 2 passes are the table-tennis H3 call precision and v2 on
  unseen markets in the IS period, neither a tradable book.
- old `"blind tests: 2 pass · 4 fail"` -> new `"blind tests of tradable books: 0 pass · 4 fail"`. Reconciled meanwhile
  in README, Devpost, deck notes (slide 8) and QA_PREP §7.

**V6. "6.9 ms on an NVIDIA L4"** (pipeline segment, `make_video_60.py:1164`, `:3632`).
- The paper, deck and README use 4.6 ms = per-frame p50 to call-ready; 6.9 ms = p50 per emitted call, same run
  (`results/engine/online_vs_offline.json`, `stream.after_startup`).
- old `"frame to call, p50 (NVIDIA L4)"` -> new `"per emitted call, p50 (NVIDIA L4)"`. Labelled meanwhile everywhere else.

**V7. Narration at 5.2 s: "Our computer vision calls the point before the ball lands"** (strategy segment).
- True for table tennis (real footage); tennis is simulated. If re-voiced: `"…calls the point before the ball lands
  (in table tennis today)…"`. The deck's slide 1 now says "table-tennis points"; slide 2 carries the label.

**V8. End card** (`make_video_60.py:1859` END_LINE) credits OpenTTGames, the tennis clip and the AI voice; it does
not credit the ElevenLabs music bed. old `"Voice: AI (ElevenLabs)"` -> new `"Voice and music: AI (ElevenLabs)"`.
README, Devpost and the deck now credit both.

## Paper (`docs/paper/note.tex.j2` -> `note.tex`, `docs/NOTE.pdf`)

**P1. Disclosure paragraph omits pre-existing evaluation weights and the video's third-party media.**
- Location: `note.tex` "Disclosure." paragraph (end of the main text, ~line 284-287).
- old: `"Open-source parts we did not build: the OpenTTGames dataset and the BlurBall and WASB model weights, cited above."`
- new: `"Open-source parts we did not build: the OpenTTGames dataset, the BlurBall and WASB model weights, and the
  TrackNet weights and TennisProject/TennisCourtDetector code (used unmodified, for evaluation only), cited above.
  The video uses a licensed Pexels stock rally and an AI voice (ElevenLabs)."` (the last sentence only if space allows;
  README and Devpost carry it).

**P2. Page budget (resolved at `e62957a`; keep it so).** During the final builds `results/paper/checks.json` and
`docs/paper/note.aux` flipped between 5 and 6 main pages. At `e62957a`: `main_pages` = 5, 13 pages in all, no `fail`,
`\label{lastmain}` on p. 5. Any later paper edit must keep `checks.json::main_pages` = 5 (`bash run.sh redteam`
check 7 reads it; COMPLIANCE.md row 2 takes its status from it at build time).

**P3. Peek-log count.** The paper says 77 reads of held-out data. `results/oos_peeks.log` has 77 lines in the working
tree but 76 at HEAD: line 77 (`2026-10-04T02:02:51Z maker v1 live paper session (B) START …`) is uncommitted. Commit
it (`git add results/oos_peeks.log`), or a clean clone counts 76 against the paper's 77.

**P4. The forest plot is no longer in the paper** (no `\label{fig:forest}`; `figA4_forest` is not included). The deck's
slide 8 still shows `results/paper/v2/figA4_forest.png` and now cites it as a repo figure ("the paper lists the same
tests in Table A1"); if the figure returns with its label, the deck cites the paper figure automatically on rebuild.

## After the paper freezes

Run, in order: `python scripts/build_paper.py` (if not already), `bash run.sh docs` (README, Devpost text, compliance
map and `results/paper/labels.json` from the frozen labels), `.venv/bin/python docs/deck/build_deck.py`,
`.venv/bin/python docs/deck/render_thumbs.py`, `bash run.sh redteam`; then commit `README.md docs/DEVPOST.md
docs/COMPLIANCE.md results/paper/labels.json docs/deck/ results/redteam/acceptance.json`. `bash run.sh docs --check`
must exit 0 (it also fails if `results/paper/labels.json` is stale).

## Paper revision of 2026-10-04 (evidence pass): audit result and what is left outside the paper

Written by the paper owner after rebuilding `docs/NOTE.pdf` (5 main pages + 2 pages of references and disclosure +
7 appendix pages = 14; `results/paper/checks.json` has no `fail`; smallest main-text span 11.0 pt; 0 margin
violations; `scripts/redteam_acceptance.py --strict`: 0 FAIL, 0 WARN). `results/paper/numbers.json`: no existing value
changed; 32 keys added (`tn.real.*`, `gate.*`, `plat.*`, `ft.months.cal`, `decay.fast.{12,23}.*`).

**What changed in the paper.** Abstract and Summary lead with the evidence (who sets the price, the fast tier in all
11 months, no factor exposure, the edge halving within 1-2 s, the first second of delay costing $42-74 a day, 54 ms),
then the conditional CV profit at 0.5 / 1 / 3 s (pre-registered first, post hoc second), then the failures in one
sentence. New in the main text: the tennis tracker on the Pexels rally (89% of 300 frames, 48/48 spot-checks, court
lines 0.36 px; no in/out calls); the rally gate replayed on the engine's held-out call log (new
`scripts/rally_gate_eval.py` -> `results/engine/rally_gate_eval.json`: at the pre-set 2.0 s it removes 5 of the 7
calls on unlabelled balls, 4 of 5 between rallies, keeps 3 of 5 correct calls, 2 at 0.5-0.8 s; about 8 phantom calls an
hour remain); the plateau (55/55 sizing rules with IS per-share CI above zero, Sharpe 4.1-16.8; PBO 9-24% by block
choice; the latency curve never rises by more than $0.09 a day across 14 delays). The event logo sits in the title
block. Appendix B gained the tennis-clip, rally-gate and TT5 decay-test rows; Appendix D counts the 4 gate values as
sensitivities that chose nothing. P1 (disclosure) is fixed in the paper.

**Audit of REQUIREMENTS.md items 1-73 against the PDF and repo.** Every item the paper can carry is met: 1-10, 16-17,
19-21, 24-37, 40-45 (5 pages, 11 pt, margins, hypothesis first, IS/OOS net of costs, all six metrics both periods,
risk and capacity sections, variant count, outline, sources cited incl. the Pexels clip and the TrackNet /
TennisProject / TennisCourtDetector weights, disclosure of pre-existing parts, holdout and peeks, walk-forward tuning,
look-ahead disclosed, costs in bps and doubled, data problems, plateau and deflated Sharpe, Sharpe-above-3 check,
regimes, citations, factor regression, capacity in $ and share of volume, limits / de-risking / tail, failures, no
real money, licences). Items 11-15, 18, 22-23, 38-39, 46-73 are repo, Devpost, presentation and logistics items, not
paper items; 22 (Polymarket vs the track's market list) is still the open organizer question in section G.

**Left outside the paper's files (exact fixes):**

- **E1 `reproduce.sh`** (repo owner): the paper now reads `results/engine/rally_gate_eval.json`. Add before
  `$PY scripts/build_paper.py`:
  `$PY scripts/rally_gate_eval.py   # rally gate on the engine's held-out call log -> paper sec:risk, Table A1`
  (laptop, < 2 s, reads only committed files).
- **E2 docs regeneration** (README / DEVPOST / COMPLIANCE owner): `scripts/build_docs.py --check` reports README.md,
  docs/DEVPOST.md and docs/COMPLIANCE.md STALE against the new build (numbers timestamp, 14 pages, appendix figure
  pages). `results/paper/labels.json` is already refreshed and committed with the paper. Run `bash run.sh docs`, then
  commit the three files.
- **E3 `docs/templates/COMPLIANCE.md.in` row 33** (p-hacking): append to the Evidence cell
  `; plateau in §{{ref:sec:results}}: all {{plat.sizing.pos}} sizing rules have IS per-share CIs above zero (Sharpe
  {{plat.sizing.sr}}), PBO {{plat.pbo}} across block choices, and the latency curve never rises by more than
  {{plat.lat.rise}} a day across {{plat.lat.n}} delays`.
- **E4 `docs/templates/COMPLIANCE.md.in` row 42**: `the rally gate` -> `the rally gate, replayed on the engine's
  held-out call log (removes {{gate.out.removed}} of {{gate.out.total}} calls on unlabelled balls, keeps
  {{gate.correct.kept}} of {{gate.correct.total}} correct calls; not yet safe to trade)`.
- **E5 `docs/templates/DEVPOST.md.in:103`**: old `Evaluate the coded rally-state gate against phantom calls outside
  play, and move the vision engine to tennis video.` -> new `Replace the rally gate (evaluated: at 2.0 s it keeps 3 of 5
  correct calls and leaves about 8 phantom calls an hour) with a better between-rally filter, and move the vision
  engine to tennis video.`
- **E6 `docs/deck/build_deck.py:1146`**: old `a rally-state gate is coded, not yet evaluated.` -> new `a rally-state
  gate is coded and evaluated: at 2.0 s it removes 5 of 7 calls on unlabelled balls but keeps only 3 of 5 correct ones
  (~8 phantom calls an hour remain).` Rebuild the deck.
- **E7 `docs/QA_PREP.md:416-418` and `docs/RISK.md:45-46, 280, 283`**: replace `not yet evaluated` (and `not yet
  evaluated on the full engine event log`) with `evaluated by scripts/rally_gate_eval.py
  (results/engine/rally_gate_eval.json): at 2.0 s it removes 5 of the 7 calls on unlabelled balls (4 of 5 between
  rallies) but keeps only 3 of the 5 correct calls (2 at 0.5-0.8 s); about 8 phantom calls an hour remain`.
- **E8 `engine/README.md:676-680` and the comment at `engine/strategy.py:102-106`** (engine owner; comment only, no
  behaviour change): `has not been evaluated on the full engine event log` -> `evaluated on the held-out call log by
  scripts/rally_gate_eval.py (results/engine/rally_gate_eval.json): keeps 3 of 5 correct MISS calls, removes 5 of 7
  calls on unlabelled balls`.
- **E9 `research/compliance/INTEGRATION_TODO.md` R-3**: QUEUED -> DONE (laptop replay of
  `results/engine/online_events_L4.jsonl` through `CourtsideStrategy.on_call`; the target "4 scored true positives
  kept" is NOT met: 2 of the 4 early true positives are kept at 1.2-2.0 s, because the engine made no bounce call in
  the 6-17 s before test_4 frames 5751 and 9837).
- **E10 (P3, still open) `results/oos_peeks.log`**: line 77 is still uncommitted (the paper says 77); commit it.
- **E11 `results/redteam/acceptance.json`**: the paper owner's strict run passed (0 FAIL, 0 WARN) but its rewrite of
  this file was reverted (not a paper file). After E2, run `bash run.sh redteam` and commit it.
- **V1-V8** (video) are unchanged by this pass.
