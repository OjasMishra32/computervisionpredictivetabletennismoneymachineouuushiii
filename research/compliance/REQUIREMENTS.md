# Systematic Trading track: every requirement, rule, deadline and rubric item

Extracted on Sat 2026-10-03 at about 14:10 EDT from the live sites (read-only). Raw text for every source is in
`research/compliance/raw_site_text.txt`. Quotes are verbatim, with curly apostrophes as they appear on the site.

**Sources (tags used below)**

| Tag | Source |
|---|---|
| TP | https://www.gqhacks.com/tracks/systematic-trading, live chunk `SystematicTrackPage-tcbiXROm.js`, cited by section (Overview, Hypothesis, Data, Webull Starter, Backtesting, Pitfalls, Risk & Capacity, Quant Note, Judging, Submitting) or widget (checklist, note blueprint, rubric simulator, backtest lab, holdout planner, capacity dial) |
| SHELL | the same page, shared deadline-clock component `shell-Di37dqBY.js` |
| HOME | https://www.gqhacks.com home page (`index-CNWGO2eT.js`): schedule, FAQ, track cards |
| MV | https://www.gqhacks.com/tracks/systematic-trading/massive (Massive bonus subtrack) |
| DP / DP-rules / DP-dates / DP-res | https://gqhacks.devpost.com overview, /rules, /details/dates, /resources |
| HG | Hacker Guide, https://gqhacks.notion.site/hacker-guide (rendered in a browser, schedule toggles expanded) |
| TERMS | Gator Quant Hacks Participant Terms v1.0 (effective 2026-09-13), github.com/dominickdupuy/gatorqh/blob/main/TERMS.md, linked from the site footer, Devpost and HG |

**Precedence.** TP says: "If anything here conflicts with the brief or an organizer announcement, go with the brief or the announcement." The "Systematic Trading Track Participant Brief" it summarizes is **not linked anywhere** in the live bundles. Only the Quant and Hardware tracks have PDFs. TERMS 14.1 says Track Rules control on competition procedure.

---

## A. Submission artefacts

1. **Two deliverables, both mandatory.** "Submit two things on Devpost: your quant note as a PDF and a link to a public GitHub repo. Both are required. A note without code, or code without a note, won’t be judged." [TP Submitting] The hero spec reads "DELIVERABLES · NOTE + CODE". [TP hero]
2. **Note: a PDF of at most 5 pages.** "The quant note is a PDF of at most five pages, figures and tables included." [TP Quant Note] The checklist adds "Quant note as a PDF, 5 pages or fewer (excluding references and appendix)". [TP checklist]
3. **Note formatting.** "Use 11pt font or larger and standard margins." [TP Quant Note] Blueprint tags: "5 PAGES INCL. FIGURES & TABLES", "11PT FONT OR LARGER", "STANDARD MARGINS", "REFERENCES & APPENDIX DON’T COUNT". [TP note blueprint]
4. **The appendix may go unread.** "References and an optional appendix of extra charts don’t count toward the limit, but judges aren’t required to read the appendix." [TP Quant Note] Also: "anything that matters belongs in the five pages." [TP note blueprint]
5. **Hypothesis stated before results.** Checklist: "Hypothesis stated before results". Blueprint: "State it before the results, not after." [TP]
6. **In-sample and OOS reported separately, net of costs.** Checklist: "In-sample and out-of-sample results reported separately, net of costs". Blueprint (Results): "Report in-sample and out-of-sample results separately. Every number net of costs." [TP]
7. **Minimum metrics, for both periods.** Checklist: "Sharpe, max drawdown, turnover, and an equity curve included". The Backtesting rule asks for more: "For in-sample and out-of-sample separately: annualized return, volatility, Sharpe, max drawdown, turnover, and an equity curve." [TP Backtesting, "REPORT THE MINIMUM"] Report all six for both IS and OOS.
8. **Risk and capacity sections.** "Risk management and liquidity/capacity sections included". [TP checklist]
9. **Variant count disclosed.** "Number of strategy variants tested disclosed". [TP checklist] Also "What didn’t work, and how many variants you tried in total." [TP Overview, "THE FAILURES TOO"]
10. **Suggested note outline (8 sections, 5.0 pages in total).** Source: TP note blueprint, which notes "Budgets are a suggested starting point."
    - SUMMARY (0.25 p): "The strategy", "The edge", "The headline out-of-sample results".
    - ECONOMIC HYPOTHESIS (0.5 p): "Who is on the other side of your trade, and why the opportunity persists." Cover risk premium, behavioral bias, structural/institutional constraint, or liquidity provision.
    - DATA & UNIVERSE (0.5 p): "Instruments, frequency and date range", "Sources (cite every one)", "How you handled survivorship, corporate actions and missing data".
    - METHODOLOGY (1.0 p): signal construction, portfolio construction, position sizing, rebalancing frequency, execution assumptions.
    - RESULTS (1.25 p): annualized return, volatility, Sharpe ratio, max drawdown, turnover, an equity curve.
    - RISK MANAGEMENT (0.5 p): position and exposure limits, stop or de-risking rules, factor and correlation exposure, tail and regime risk.
    - LIQUIDITY & CAPACITY (0.5 p): trading costs, slippage, market impact, and "Roughly how much capital the strategy could run before the edge erodes".
    - LIMITATIONS & NEXT STEPS (0.5 p): "What you would test with more time", "What could break the strategy".
    - "FEEDS" map from section to criterion: Summary → EF + Perf; Hypothesis → EF + Innovation; Data → Perf; Method → Innovation + Perf; Results → Perf; Risk → Risk; Liquidity → Liquidity; Limitations → Risk + Perf.
11. **Public GitHub repo with a README and a dependency file.** Checklist: "Public GitHub repo linked, with a README and dependency file". Banned: "A zip upload instead of a public GitHub link". [TP Submitting]
12. **What the repo must contain.** [TP Submitting, "WHAT GOES IN THE REPO"]
    - "A README with setup steps and the single command or notebook that reproduces your headline results"
    - "A dependency file: requirements.txt, environment.yml, or equivalent"
    - "All signal, backtest and analysis code"
    - "Data download scripts, or instructions for getting the data"
    
    The example layout is labelled "EXAMPLE LAYOUT · YOURS CAN DIFFER". It shows README, requirements, `.env.example` ("keys stay out of git"), `data/download.py` ("download scripts only"), `src/`, and `run_all.py` ("reproduces the note").
13. **One command reproduces the headline numbers.** Checklist: "One command or notebook reproduces the headline numbers". "Judges will spot-check that your code runs and that the numbers in your note match what it produces." [TP Submitting]
14. **Never commit secrets or licensed data.** The "NEVER COMMIT" list is "Raw licensed data", "API keys", and "A zip upload instead of a public GitHub link". Checklist: "No API keys or licensed raw data committed". [TP] The Webull starter adds "Never commit .env." TERMS 15.3: "No Participant shall redistribute, resell, publish, or retain licensed data beyond the period permitted by the provider, scrape beyond permitted limits, or share any application programming interface key or credential."
15. **All team members listed on Devpost.** "All team members listed on Devpost". [TP checklist]
16. **Every data source cited in the note.** "CITE EVERY SOURCE · Sponsor data is optional. Free public sources are allowed. Every source you use is cited in the note." [TP Data, rules] Libraries and research must be cited too (see 37).
17. **Disclose pre-existing components when submitting.** TERMS 14.2: "All work submitted must be created by the submitting team during the Event, except for open-source libraries, publicly available datasets, and pre-existing components that the applicable Track Rules permit and that the team discloses at the time of submission."
18. **Code can be pushed until the deadline.** "Note and repo link due on Devpost. You can keep pushing code until 11:00 AM." [TP Overview, "DEVPOST CLOSES"] See 60 for the cutoff.

## B. Method rules

19. **Write the hypothesis before any backtest.** "Pick a market and write down why you think there’s an edge in it. Do this before you run a single backtest." [TP Overview timeline, FRI 7:15 PM] "Before you look at any results, write down who’s taking the other side and why the opportunity hasn’t gone away." [TP Hypothesis]
20. **Commit the hypothesis first.** "Commit your hypothesis to the repo before your first backtest. The commit timestamp shows judges it came before the results." [TP Hypothesis, "COMMIT IT FIRST"]
21. **Hypothesis template.** "We expect [universe] to [behavior] over [horizon] because [counterparty], and the edge persists because [persistence]. If true, we should see [prediction]; it fails if [falsifier]." It is stamped "WRITTEN BEFORE RESULTS". Edge sources offered: risk premium, behavioral bias, structural constraint, liquidity provision. [TP hypothesis builder]
22. **Market scope.** "Any liquid, publicly traded market works. Pick one you can get clean data for." Chips: EQUITIES, ETFS, FUTURES, FX, OPTIONS, CRYPTO. [TP Data] The lede says "Pick a liquid, publicly traded market you can get clean data for." Devpost may disqualify a submission that "uses data not permitted for its track". [DP-rules]
23. **Data sources.** "Registered teams get sponsor data from Databento and Webull, and free public sources are fine too." [TP Data] HG: "Outside data: allowed". The listed free sources are FRED and the Ken French Library, the latter "for benchmarking against market, value and momentum". [TP Data]
24. **OOS holdout size.** "For this track: the most recent 20% of your history or the most recent 2 years, whichever is shorter." [TP key terms] The planner reads "RULE: MOST RECENT 20% OR 2 YEARS, WHICHEVER IS SHORTER". [TP holdout planner]
25. **Set the holdout aside early and don't look at it.** "set aside the most recent stretch as your out-of-sample period and don’t look at it." [TP timeline, FRI NIGHT]
26. **Evaluate the holdout once.** "Evaluate it once, at the end. If you look at it and then go back and change things, it isn’t out-of-sample anymore." [TP holdout planner] Also "Don’t touch the out-of-sample period until the end, then evaluate it once." [TP Pitfalls, "LEAKING THE TEST SET"]
27. **Report the OOS result, good or bad, and every peek.** "Run the out-of-sample period once and report the result, good or bad." [TP timeline, SAT NIGHT] "In real life you can’t un-see a result. Report every peek in your note." Also "Out-of-sample came in well below in-sample. Report it anyway. Judges want to see that." [TP backtest lab]
28. **Tune only inside the in-sample period.** "Tune with walk-forward folds inside the in-sample period: always train on the past and validate on what comes next. Leave a purge gap so overlapping labels don’t leak across the boundary. The locked period stays untouched." [TP holdout planner] Also "Use walk-forward or cross-validation that respects time order." [TP Pitfalls, Overfitting]
29. **No lookahead.** "Lag every signal at least one bar. Trade at the next open or close. Use point-in-time data when it exists." [TP Pitfalls, Lookahead] "If a signal uses today’s close, you can’t also trade at today’s close." [TP Backtesting, "LAG EVERY SIGNAL"] Lookahead includes "revised economic data, future index membership". [TP Pitfalls]
30. **Everything net of costs, with the cost justified.** "Every reported result is net of transaction costs. State the cost in bps per trade and justify it." [TP Data, rules, "NET OF COSTS"] Also "Pick a cost for your market and explain where the number came from." [TP key terms, Basis point]
31. **Show what happens when costs double.** "Report everything net of commissions, spread and slippage, and show what happens when costs double. If the edge disappears, say so." [TP Backtesting, "DOUBLE THE COSTS"] The Pitfalls section repeats this under "IGNORING COSTS". [TP Pitfalls]
32. **Data problems to handle, and explain in the note.**
    - Survivorship: "Use a point-in-time universe, or say the bias is there and estimate how much it matters."
    - Corporate actions: "Use adjusted data and say how it was adjusted."
    - Missing data: "Say whether you filled or dropped them, and never fill a gap with data from after it."
    
    [TP Data, "DATA PROBLEMS TO HANDLE (AND EXPLAIN IN THE NOTE)"]
33. **Guard against p-hacking and data snooping.** "Write the hypothesis first and report how many variants you tried. Show that nearby parameter values also work; a broad plateau is far more convincing than one sharp peak." [TP Pitfalls] Picking the best parameter "after looking is one more trial to disclose." [TP backtest lab] The overfitting lab names "the Deflated Sharpe Ratio" as the fix. [TP Pitfalls]
34. **Avoid overfitting.** "Keep the parameter count low and favor simple rules with an economic reason behind them." [TP Pitfalls]
35. **Put Sharpe in context.** "Report max drawdown, skew and worst month next to Sharpe. If you get a Sharpe above 3 on daily data, assume something is wrong until you find out what." [TP Pitfalls, "MISLEADING SHARPE"] Also "A Sharpe above 3 on daily data usually means a bug. Check before you celebrate." [TP key terms]
36. **Break results down by year or regime.** "Break results down by year or regime and talk about it in the note." [TP Pitfalls, "REGIME DEPENDENCE"] The lab adds: "Check the by-year bars to make sure it isn’t all from one good period." [TP backtest lab]
37. **Originality and copying.** "Open-source libraries and published research are fine, cited. Copying a strategy is allowed only if you clearly extend it and say what is new." [TP Data, rules, "EXTEND, THEN CITE"] HG: "Pre-existing work: not allowed. Everything you submit must be built during the event." Devpost may disqualify any submission that "plagiarizes, misrepresents original work, uses data not permitted for its track, cannot be reproduced from submitted code, or violates the Code of Conduct." [DP-rules]
38. **AI tools.** "AI TOOLS ALLOWED · You’re still responsible for every line of code and every claim, and judges may ask you to explain any of it." [TP Data, rules] HG: "AI tools: allowed". TERMS 14.3: AI assistants are "permitted unless the applicable Track Rules provide otherwise." The track asks for no AI disclosure.
39. **Any language.** "ANY LANGUAGE" [TP hero]. "Use any language; most teams use Python." [TP Overview] The Webull starter is optional and is "evidence for your note". [TP Webull Starter]
40. **Check the simple explanation first.** "When a result looks good, look for a simpler reason first. Usually it’s a bug, a bias, or exposure to something well known like market beta, momentum or value." [TP Pitfalls] Under factor exposure: "Regress your returns on those factors to find out." [TP Risk & Capacity]
41. **Capacity analysis.** "Size positions as a fraction of average daily volume and estimate capacity in dollars." [TP Pitfalls and capacity dial] "state your own cost, spread and impact assumptions for your market, and show how results change when costs double." [TP capacity dial, "IN YOUR NOTE"]
42. **Risk controls to describe.** [TP Risk & Capacity]
    - Limits: "Limits per name, per sector, and on gross and net exposure. What’s the most you can lose on a single position?"
    - De-risking: "Rules, set in advance, for when you cut size and when you scale back in."
    - Tail and regime: "What happens in a crash, a volatility spike, or a market that stops trending?"
43. **Keep a record of failures.** "Expect most ideas to fail here. Keep a list of the ones that did, because it goes in your note." [TP timeline, SATURDAY] Also "report what you found, including what didn’t work." [TP Overview]
44. **No real-money trading.** TERMS 5.3: "Participants shall not connect a funded brokerage or exchange account to any Event activity." The track page says "Paper and live trading aren’t scored." [TP Webull Starter]
45. **Third-party licences and terms of service.** The submission must not violate "the license or terms of service of any tool, dataset, or platform used in its creation." [TERMS 14.4] Data access is "for educational and competition use only." [TERMS 15.1]
46. **Judges may re-run your code.** Submitting grants a licence to "access, execute, review, evaluate, score, and reproduce the submission for the purpose of judging and verifying results, including re-execution against held-out data". [TERMS 16.2(a)]

## C. Rubric criteria

47. **Scoring structure.** "Judges score five criteria from 1 to 10, for a total out of 50." [TP Judging] Hero: "SCORED · 5 × 10 = 50". The four bands are labelled "1–3", "4–6", "7–9", "10", so the top band is a single score. [TP rubric simulator]
48. **Criterion 1: Economic Foundation.** "Strength of the economic hypothesis behind the strategy". [TP]
    - 1–3: "Hypothesis lacks clarity or logical foundation. No clear rationale for why the strategy should work."
    - 4–6: "Moderate understanding of economic drivers, but with weak or incomplete logical support."
    - 7–9: "Strong economic rationale with clear articulation of why the strategy should perform. Logical, well-supported arguments."
    - 10: "Exceptional economic understanding, with highly compelling and well-evidenced reasoning for the strategy's success."
49. **Criterion 2: Innovation.** "Creativity and distinctiveness of the strategy". [TP]
    - 1–3: "Generic or common strategy with no clear differentiation."
    - 4–6: "Some innovative aspects, but relies on established frameworks or ideas."
    - 7–9: "Strong differentiation from traditional strategies, with unique or novel elements."
    - 10: "Highly innovative, groundbreaking approach that is original and distinct from conventional strategies."
50. **Criterion 3: Risk Management Plan.** "Comprehensiveness and effectiveness of risk controls". [TP]
    - 1–3: "Minimal or no risk management outlined. Little understanding of key risks."
    - 4–6: "Basic risk management plan, but lacking depth or thoroughness."
    - 7–9: "Comprehensive framework with clear plans to mitigate identified risks."
    - 10: "Highly detailed and effective approach, with multiple contingencies and a thorough understanding of strategy risks."
51. **Criterion 4: Liquidity & Capital.** "How well the strategy accounts for liquidity and capital deployment". [TP]
    - 1–3: "No clear analysis of liquidity or capital needs. Strategy might be impractical in real markets."
    - 4–6: "Some consideration of liquidity and capital, but with gaps or oversights."
    - 7–9: "Strong understanding of liquidity and capital needs, with realistic and practical deployment."
    - 10: "Excellent, thorough analysis demonstrating deep market knowledge and practical application."
52. **Criterion 5: Performance & Analytical Evidence.** "Use of historical data or other evidence to demonstrate the strategy's potential". [TP]
    - 1–3: "Little to no evidence. No meaningful analysis supporting performance."
    - 4–6: "Some evidence, but limited depth or rigor. Partial performance analysis."
    - 7–9: "Strong use of data and analysis. Well-reasoned performance expectations."
    - 10: "Exceptional analytical rigor, with thorough and convincing evidence of effectiveness."
53. **Score cap on criterion 5.** "If judges can’t run your code, or it gives materially different numbers than your note, your Performance and Analytical Evidence score is capped at 4. The same cap applies if they find lookahead bias or tuning on the out-of-sample period." [TP Judging, "SCORE CAP"] The rubric simulator's two conditions are "JUDGES CAN RUN OUR CODE AND IT MATCHES THE NOTE" and "NO LOOKAHEAD, NO TUNING ON OUT-OF-SAMPLE". The lab adds: "Judges cap criterion 5 at 4 for this."
54. **Code backs criterion 5.** "Code isn’t scored on its own, but it supports your Performance score, and judges will spot-check that it runs and matches your note." [TP Judging]
55. **Tie-break.** "Performance & Analytical Evidence first, then Economic Foundation." [TP rubric simulator, "TIES"]
56. **No P&L leaderboard.** "There’s no P&L leaderboard. Returns only count as evidence for your argument." [TP] Also "Judges would rather see a Sharpe of 0.6 you can defend than a 4 you can’t explain." [TP] And "A modest strategy with a solid rationale will score better than a huge backtest that doesn’t hold up." [TP Overview]
57. **What judges want to see.** [TP Overview]
    - "A HYPOTHESIS UP FRONT": "An economic reason for the edge, written down before you saw any results."
    - "A FAIR TEST": "Realistic costs, and an out-of-sample period you never tuned on."
    - "THE FAILURES TOO": see item 9.
    - "CODE THAT RUNS": "A judge can run it and get the same headline numbers that are in your note."
58. **How sections map to criteria.** Avoiding the pitfalls helps "on Economic Foundation and Performance" [TP Pitfalls]. "Two of the five judging criteria are about what comes after the backtest: how you control risk, and how much money the strategy could manage before trading costs and market impact eat the edge." [TP Risk & Capacity] The hypothesis is "the core of your Economic Foundation score". [TP Hypothesis]
59. **Judges and finality.** Devpost lists the judges as University of Florida faculty, Jane Street, Citadel, Databento and MLH. [DP] "Judges' decisions are final." [DP-rules] TERMS 17.2 reserves the right "to correct scoring or administrative errors identified after announcement." TERMS 17.7 allows disqualification and reclaiming a prize if a violation "is discovered after the award."
    - **Massive bonus (optional; applies only if you enter it).** It requires Massive 8-K and options data. "A Massive entry is a Systematic Trading submission, scored on the track’s rubric like every other." GQH sends its ten best entries to Massive.
    - Massive's own 100 points: Hypothesis and novelty 30, Analytical rigor 30, Sealed-window replication 20, Trade realism 10, Communication 10.
    - The notebook must take "a start date and an end date as inputs", and the sealed window replaces the 20% holdout. [MV] HG: "To participate, your project must meet all Systematic Trading track requirements."

## D. Presentation

60. **Live 5-minute presentation with Q&A, Sunday 1:00–3:00 PM, Matthews Suite.** The home page FAQ says "live 5-minute presentations with Q&A from 1:00 to 3:00 PM". [HOME] The schedule lists "Matthews Suite · live presentations: 5 minutes + Q&A". [HOME] HG: "Expo & Judging - Matthews Suite, 1:00 PM - 3:00 PM · Live team presentations (5 minutes + Q&A)."
61. **Sign up for a slot TODAY (Sat Oct 3), 5:00–6:00 PM, Grand Ballroom.** HG: "Track Check-Ins & Presentation Sign-Ups - Reitz Union Grand Ballroom, 5:00 PM - 6:00 PM · Mid-event team check-ins. Sign up here for a Sunday presentation slot." HOME: "Track Check-ins · Grand Ballroom · sign up for a Sunday presentation slot".
62. **The track page does not specify the presentation format.** HG says "presentation format, judging rooms, and which teams present live on Sunday are in the track instructions on gqhacks.com". However, the live track page has no presentation text: no slide requirement, slide count or demo rules. The only format given is "5 minutes + Q&A". Confirm at check-in or in #ask-organizers.
63. **Every member must be able to answer questions.** "Every team member should be able to explain the strategy if judges ask follow-up questions." [TP Data, rules, "EVERYONE CAN EXPLAIN"] Also "judges may ask you to explain any of it." [TP, AI rule]

## E. Logistics

64. **Deadline: Sun Oct 4, 11:00 AM Eastern (EDT), both Devpost and the final code push.**
    - Devpost: "Deadline: Oct 4, 2026 @ 11:00am EDT". [DP]
    - TP: "DEADLINE · SUN OCT 4 · 11:00 AM".
    - SHELL: "DEVPOST SUBMISSION · SUN OCT 4 · 11:00 AM · Late submissions are not judged." and "FINAL CODE PUSH · SUN OCT 4 · 11:00 AM · Commits after 11:00 AM are not reviewed." The clock is labelled "EASTERN TIME" and coded as `Date.UTC(2026,9,4,15,0,0)`, which is 11:00 EDT.
    - HG: "Hacking Ends / Submission Deadline: All Other Tracks - 11:00 AM · All other submissions must be on Devpost by 11:00 AM."
65. **Changed today.** The cached copy (about 03:44) said 10:00 AM for Systematic and Hardware and 8:00 AM for Quant Puzzles. The live site now says 11:00 AM and 9:00 AM. The 11:00 AM code-push line did not change. See section F.
66. **Devpost window and winners.** Submissions run "October 02 at 6:45pm EDT" to "October 04 at 11:00am EDT". Devpost lists "Winners Announced October 04 at 6:00pm EDT". [DP-dates] The site and HG say winners are announced "at the closing ceremony at 3:40 PM". The closing ceremony starts at 3:35 PM in the Grand Ballroom and the event ends at 4:00 PM. [HG]
67. **Team size and roster.**
    - HG: "Team size: 1 to 4 people" and "Solo entries: allowed".
    - DP-rules: "Team members must attend in person." and "Each participant may join only one team, and each team may submit to only one track."
    - DP overview: "Teams may form and change until hacking begins on Friday. After that, rosters are locked."
    - DP sidebar: "Team required".
68. **Eligibility.** "at least 18 years old as of October 2, 2026", enrolled at "an accredited U.S. college or university". [DP-rules] "Proof of enrollment, such as a valid student ID, may be requested at check-in and before prizes are awarded." [DP-rules] Employees of sponsoring firms, organizers, judges and their families "are not eligible for prizes". [DP-rules] TERMS 3.1 also admits recent graduates, within 12 months.
69. **Rule changes and where announced.** "Organizers reserve the right to modify the schedule, format, prizes, or rules at any time. Material changes will be announced in Discord and posted in the Hacker Guide." [DP-rules] "Competitors should not rely on unofficial deadlines or room assignments." [HG] Watch #announcements. Discord invites differ by source: TP uses discord.gg/BNB82dKdf, DP uses discord.gg/9qPMtN4UB, HG uses discord.gg/kQX9ZtWFHG.
70. **Conduct.** "All participants ... must follow the Gator Quant Hacks Terms and the MLH Code of Conduct". [DP-rules] TERMS 14.5 disqualifies submissions with "malicious code, unlawful content". Questions go to gatorquanthacks@gmail.com, urgent ones to dominickdupuy@ufl.edu. [DP-res]
71. **Back up your own work.** "Each Participant is solely responsible for backing up the Participant's own work." The organizer has no liability for "lost code, data, or submissions". [TERMS 11.4] Data access may be "rate-limited, delayed, interrupted, or withdrawn". [TERMS 15.4]
72. **Prizes.** Systematic Trading 1st: "Acer Nitro ED340CUR 34" curved monitor for each team member, plus 3 months of ElevenLabs Pro". 2nd: "Samsung Galaxy Watch8 (40mm) for each team member". [HG] "Physical prizes are one per team member." [HG] TERMS 17.3: prizes are non-cash and non-transferable. Massive subtrack 1st: "Apple AirPods 4 for each team member". [HG]
73. **Submit even if unfinished.** "What if my project isn't finished or has bugs? Submit it anyway." [HG FAQ]

## F. What changed: live site vs cached copy (docs_cache, about 03:44 today)

I normalised the chunk-hash names and diffed the JS token by token. Bundle sizes are byte-identical. **Only deadline times changed**:

- **TP:** "SUN 10:00 AM" → "SUN 11:00 AM" in four places: the hero spec, the story stamp, the "DEADLINE" card, and "ALL CHECKED · SUBMIT ON DEVPOST BEFORE 11:00 AM".
- **MV:** "SUN 10:00 AM · DEVPOST CLOSES" → "SUN 11:00 AM". Checklist "Submitted on Devpost by 10:00 AM" → "11:00 AM".
- **HOME:** the Sunday schedule changed from "08:00 AM Quant Puzzles Submissions Due" to "09:00 AM", and from "10:00 AM Devpost Submissions Due (Hardware and Systematic Trading tracks)" to "11:00 AM". The FAQ changed from "by 10:00 AM Sunday (8:00 AM for ...)" to "by 11:00 AM Sunday (9:00 AM for the Quantitative Puzzles track)".
- **Unchanged:** the code-push line ("until 11:00 AM") and all rubric, rule, checklist, page-limit, holdout and cap text.
- **Not diffable:** the old shell chunk is no longer served and was not cached.
- **New beyond the cache:** Devpost (overview, rules, dates, resources; no updates or discussions posted), the Hacker Guide and the Terms.

## G. Conflicts and ambiguities to resolve (ask in #ask-organizers or at today's 5 PM check-in)

- **Team rule.** DP shows "Team required", but DP-rules and HG allow solo entries.
- **Winners time.** Devpost says 6:00 PM. The site and HG say 3:40 PM at the closing ceremony.
- **Minimum metrics.** The checklist lists four (Sharpe, max DD, turnover, equity curve). The Backtesting rule lists six (it adds annualized return and volatility) for IS and OOS separately. Report all six.
- **Pre-existing work.** HG says "not allowed". TERMS 14.2 allows disclosed pre-existing components that Track Rules permit. TP allows cited libraries and research, and a copied strategy only if it is clearly extended. Disclose anything that pre-dates Oct 2, 7:15 PM.
- **Market scope.** TP says "Any liquid, publicly traded market". Its chip list (equities, ETFs, futures, FX, options, crypto) does not name prediction or event-contract markets such as Polymarket or Kalshi. Devpost can disqualify "data not permitted for its track". COURTSIDE trades Polymarket, so get organizer confirmation in writing (Discord).
- **Presentation format.** HG points to the track page for it, but the track page has none (item 62).
- **Missing brief.** TP defers to a "Participant Brief" that is not published on the site; check Discord for it.

## H. Watch items for COURTSIDE (requirement-driven; verify, not verified here)

- Item 35: the headline Sharpe is far above 3, so the note must explain why. Report max DD, skew and worst month next to it.
- Items 26–27 and 53: every OOS look must be in `results/oos_peeks.log` and the note. Re-tuning after a peek caps criterion 5 at 4.
- Items 13 and 53: `reproduce.sh` must regenerate the note's headline numbers exactly. A mismatch also caps criterion 5 at 4.
- Items 2–4: rebuild `docs/NOTE.pdf` and confirm it is ≤ 5 pages, ≥ 11 pt font and standard margins, with nothing critical only in the appendix.
- Item 7: report annualized return and volatility for IS and OOS too, not only Sharpe, max DD and turnover.
- Items 15 and 67: every team member must be on the Devpost entry and attend in person.
- Item 61: presentation sign-up is today, 5:00–6:00 PM, Grand Ballroom. Rehearse the deck to 5 minutes.
- Item 64: the Devpost submission and the last commit must both land before 11:00 AM EDT Sunday.
