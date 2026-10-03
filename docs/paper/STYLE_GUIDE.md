# COURTSIDE quant note: style guide for the build

This guide is for the agent that builds `docs/paper/` (LaTeX via tectonic), `scripts/build_paper.py` and
`scripts/paper_figures.py`. It brings together three inputs:

1. eight professional papers that I downloaded, rendered to PNG and inspected (listed in §0);
2. the track's hard rules (`research/compliance/REQUIREMENTS.md`, items 2–10, 13, 16–17, 19–37 and 40–46);
3. the team's house style (AlgoGators research papers, `docs/paper/reference/*.png`).

Where these conflict, the order of precedence is: **track rules > honesty rules > house style > journal
convention**.

---

## 0. Papers studied (read and rendered, October 3, 2026)

| # | Paper | Type | URL |
|---|---|---|---|
| P1 | Budish, E., P. Cramton and J. Shim (2015), "The High-Frequency Trading Arms Race: Frequent Batch Auctions as a Market Design Response", *Quarterly Journal of Economics* 130(4). Working-paper version dated Feb 3, 2015 | Academic WP (LaTeX, Latin Modern) | http://econweb.umd.edu/~sweeting/hft-arms-race.pdf |
| P2 | Aquilina, M., E. Budish and P. O'Neill (2022), "Quantifying the High-Frequency Trading 'Arms Race'", *QJE* 137(1): 493–564 | Published journal article | https://ericbudish.org/files/Quantifying-the-High-Frequency-Trading-Arms-Race.pdf |
| P3 | Croxson, K. and J. J. Reade (2014), "Information and Efficiency: Goal Arrival in Soccer Betting", *Economic Journal* 124(575): 62–91. WP of Jan 21, 2011 | Betting-market efficiency WP | https://repec.cal.bham.ac.uk/pdf/11-01.pdf |
| P4 | Brown, A., "Information Processing Constraints and Asset Mispricing" (Betfair in-play tennis, Wimbledon 2011–12), EFMA 2013 version; published in *Economic Journal* (2014) | Tennis betting-exchange WP | https://www.efmaefm.org/0efmameetings/efma%20annual%20meetings/2013-Reading/papers/EFMA2013_0254_fullpaper.pdf |
| P5 | Brooks, J. (2017), "A Half Century of Macro Momentum", AQR Capital Management white paper | Quant-firm white paper | https://www.aqr.com/-/media/AQR/Documents/Insights/White-Papers/A-Half-Century-of-Macro-Momentum.pdf |
| P6 | Harvey, C. R., S. Rattray, A. Sinclair and O. Van Hemert (2017), "Man vs. Machine: Comparing Discretionary and Systematic Hedge Fund Performance", *Journal of Portfolio Management* 43(4) (Man AHL authors) | Practitioner journal article | https://people.duke.edu/~charvey/Research/Published_Papers/P130_Man_vs_machine.pdf |
| P7 | Robertson, G. (2022), "Gaining Momentum: Where Next for Trend-Following?", Man Institute / Man AHL, June 2022 | Quant-firm research note | https://www.man.com/maninstitute/gaining-momentum-trend (PDF read from a mirror: https://www.bvai.de/fileadmin/Themenschwerpunkte/Hedgefonds/@Gaining_Momentum.pdf) |
| P8 | Blitz, D. (2021), "The Quant Equity Crisis of 2018–2020: Cornered by Big Growth", Robeco research paper, Feb 2021 | Quant-firm research paper | https://www.robeco.com/files/docm/docu-the-quant-equity-crisis-of-2018-2020-cornered-by-big-growth-us.pdf |

I also cite Brown, A. (2012), "Evidence of in-play insider trading on a UK betting exchange", *Applied
Economics* 44(9), on courtsiders in a Wimbledon final (https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1720045).
I read only its abstract: the open full text (HAL) is behind a bot check, and I did not get past it. All
eight PDFs and their page renders are in the session scratchpad, not in the repo, because of copyright.
**P1–P4, P6 and Brown (2012) are directly relevant to our argument and belong in the paper's References.**
P1 and P2 cover latency arbitrage and the value of speed. P3, P4 and Brown (2012) cover in-play betting
efficiency and courtsiding.

---

## (a) Structural conventions these papers share

### Title block

- **Academic (P1–P4).** Centred title, authors with footnote markers, date, then the abstract. The
  first-page footnote carries affiliations, emails, thanks and disclaimers. P2's version adds "The authors
  declare that they have no relevant or material financial interests" and "views are not those of the FCA".
- **Practitioner (P5–P8).** A big display title. Then author, role and date. P8 adds the audience ("Research
  paper · For professional investors · February 2021"). P8 also puts **three key-point bullets** under the
  title, and P7 puts a one-sentence dek there.
- **What we do.** Use the house cover style on page 1, compressed so it fits (see (b)):
  - big condensed title;
  - author line (names and emails are placeholders), University of Florida;
  - "Gator Quant Hacks 2026 · Systematic Trading Track · University of Florida";
  - October 4, 2026.

  Below that come the abstract, then the JEL and keyword lines, then §1 begins. **No cover page.**
- **First-page footnote** (unmarked, P1/P2 style), at 11 pt. It holds:
  - the reproduce command (`bash reproduce.sh`) and the repo URL;
  - "Real money: none. No funded account was connected to any event activity (Participant Terms 5.3)";
  - "CV-strategy results: assumed feed latency (licensed feed not purchased); parameters measured."

### Abstract carries the headline result in numbers

- P2 is the model to copy. Its abstract opens with the data ("We use stock exchange message data…"), then
  lists the findings as numbers. Races are "about one per minute per symbol". The modal race lasts
  "5–10 millionths of a second". Races make up "about 20%" of volume. Latency arbitrage acts like a
  "0.5 basis point" tax, and about "$5 billion" a year is at stake.
- P3 and P4 end the abstract with a plain verdict.
- **Ours.** Write about 150 words in this order:
  1. data (public Polymarket tapes, 13,084 matches);
  2. who is fast and what they earn (fast tier positive in 3/3 OOS months; copying 3 s later loses);
  3. v2 at the fast tier's own fills (OOS ¢/share, Sharpe, and *negative when fees double*);
  4. the speed curve at the simulated 1 s licensed-feed baseline, both readings;
  5. the break-even feed delay;
  6. "real money: none".
- Follow it with `JEL Classification: G14, G12, C58` and a `Keywords:` line, as in P3 and P4 (P2 uses
  D47, G10, G12, G14).

### Summary or key-findings box

- P5 has an "Executive Summary". P8 has three bullets plus a summary paragraph. P7 uses a pull-quote.
- **Ours.** §1 Summary is a box with a thin orange rule at top and bottom and 4–5 bullets, each with
  numbers:
  - Strategy;
  - Edge;
  - Headline OOS;
  - Speed (1 s baseline, both readings);
  - What failed.
- It doubles as the track's "Summary 0.25 p" (strategy, edge, headline OOS results).

### Figures and tables, or "Exhibits"

- AQR (P5) and JPM (P6) say "Exhibit n". Academic papers say Figure and Table.
- **Ours.** Use **Figure n.** and **Table n.** with bold labels, because the track talks about "figures and
  tables".
- Borrow two practitioner habits:
  - (i) the title is a **takeaway sentence**, as in P5's "Hypothetical Performance is Consistent across
    Themes and Asset Classes";
  - (ii) every float ends with a **"Source: …" line**, as in P5, P7 and P8.
- P6's Exhibit 1 puts a table, a chart and a correlation table in **one exhibit with Panels A/B/C**. Do the
  same with subcaption panels (a)(b) when two views make one point.

### How results tables are laid out

- **Horizontal rules only** (P1, P5, P6, P8): rule above the header, under the header, and at the end.
  Grouped headers get a short rule under the group name, as in P1's "Percentile" above columns 1…99.
- **Row groups** with bold group labels, as in P5: "Full Sample" then "By Decade". Ours: "Full period",
  then "By month" or "By venue regime".
- Put a **metric row label on the left and periods across**, as in P5 and P6. Ours: In sample | Out of
  sample.
- Numbers are **right- or decimal-aligned**. Units go in the column header or the row label, not in every
  cell.
- Confidence intervals go in brackets under or next to the point estimate (P3, P2).
- Under the table, give **"Notes:"** (P1, P2, P6) saying what the numbers are, the sample and the clustering.
  Then a **"Source:"** line.
- A cost or gross/net disclaimer goes in the source line. P5 writes "Returns are gross of fees and
  transaction costs. Hypothetical data has inherent limitations". Ours are net, so say "net of fees and
  traded spreads".

### How robustness and limitations are presented

- **Academic papers** (P1 §5.2.1, P2) list modelling assumptions with the reason for each, e.g. "we only
  count arbitrage opportunities that last at least 4 ms…". Robustness goes in a named subsection, with
  details in the appendix.
- **Practitioner papers** (P5, P8) put caveats in the source line of every exhibit. Examples: "hypothetical,
  backtested portfolios which ignore costs" and "Past returns are no guarantee". They close with
  "Summary and Discussion".
- **Ours.**
  - Robustness sits next to the result it qualifies: costs doubled, ½ tick and 1 tick worse entry, the
    other timing reading, wallet-clustered CIs, the deflated Sharpe.
  - Failures sit next to successes, in the same tables, not in a separate graveyard.
  - §8 "Limitations & next steps" has two lists: what could break it, and what we would test with more
    time.

### Citation style

- All eight papers cite author-year: (Fama and French 1993), Moskowitz, Ooi and Pedersen (2012).
- **Ours.** natbib author-year: `\citet{budish2015}` and `\citep{aquilina2022}`. The References come after
  page 5.
- Footnotes are for data sources and venue documents (P1, P3), e.g. "Polymarket CLOB API, accessed …".
  Keep them to 3–4 on the main pages, because they must also be 11 pt.

### Disclosure lines

- P5's last page is "Disclosures", P7's and P8's is "Important information", and P2 has a footnote.
- **Ours.**
  - The first-page footnote above.
  - A one-line disclosure at the end of the References: no real money, simulated components labelled, no
    licensed feed or footage, and the team's affiliation.
  - Do not invent a conflict-of-interest statement. Use a `[team to confirm]` placeholder if one is wanted.

---

## (b) Visual conventions

### Page and type (house style adapted to journal rigour)

The reference pages show these features:

- a light condensed display title (Oswald-like);
- body in Aptos at about 11 pt, justified;
- numbered section headings in the body sans at about 14 pt ("1   Introduction", with a wide gap after the
  number);
- a footer with a thick orange rule over a black rule and the page number centred beneath;
- the logo top right.

Build it like this:

| Element | Spec |
|---|---|
| Class | `\documentclass[11pt,letterpaper]{article}`, `geometry` with `margin=1in` exactly (footer and header sit inside the 1 in margin: `includefoot=false`, `footskip≈0.45in`) |
| Fonts (OFL, commit in `docs/paper/fonts/` with each licence) | **Use static instances, not the variable `[wght]` files, because XeTeX handles variable fonts badly.** Display: **Oswald**, `Oswald-Light.ttf` and `Oswald-Regular.ttf` from github.com/googlefonts/OswaldFont `fonts/ttf/`, plus that repo's `OFL.txt`. Body: **Source Sans 3**, which stands in for Aptos: `SourceSans3-{Regular,It,Semibold,SemiboldIt}.ttf` from github.com/adobe-fonts/source-sans `TTF/`, plus `LICENSE.md` (OFL). Math: **Fira Math**, `FiraMath-Regular.otf` from github.com/firamath/firamath release v0.3.4 (OFL), loaded via `unicode-math`. Load everything with `fontspec` using `Path=fonts/` so tectonic never looks for system fonts |
| Body | 11 pt, about 13.5 pt leading, justified, `microtype` (protrusion and expansion) |
| Section headings | `titlesec`: Source Sans 3 Regular or Semibold at 14 pt, number then `\quad\quad`, 12 pt before and 4 pt after. Subsections are 11 pt bold run-in |
| Title (page 1 only) | Oswald Light/Regular, 24–26 pt, centred, 2 lines max. Then the author line (Oswald, 13 pt), the event line (Oswald, 12–13 pt), and the date. The whole block should be no taller than about 1.9 in. Keep the cover's look but not its empty space |
| Header, pages 2+ | "COURTSIDE" in Oswald at 11 pt, top right. No logo, and no AlgoGators name |
| Footer, every page | `fancyhdr` plus TikZ: an orange rule `#F26B21` about 2 pt thick over a black rule about 1 pt thick, about 2 pt apart, the full text width. Below it, the page number centred at 11 pt |
| Links | `hyperref` with `colorlinks`. Use a dark slate (e.g. `#1F3A5F`) for links and citations, never bright blue or boxes |
| Captions | `caption`: `labelfont=bf`, `font=normalsize` (11 pt), `labelsep=period`, `justification=justified`. Table captions go above, figure captions below. `subcaption` gives (a)(b) |
| Footnotes | Redefine so they print at 11 pt: `\renewcommand\footnotesize{\normalsize}` or a `\footnotelayout`. Use them sparingly |

### Figure styling (`scripts/paper_figures.py`)

- **Vector PDF** with `pdf.fonttype=42`. Draw each figure **at its final printed size**: full width is 6.5 in,
  a half panel about 3.1 in. Include it at `width=\linewidth` with no rescaling, so the text inside stays at
  the size it was set.
- **All text in figures is 11 pt** at final size: axis labels, tick labels, legend, direct labels and panel
  letters. Register Source Sans 3 with `matplotlib.font_manager.addfont` so figures match the body.
- White background, no chart title inside the axes (the caption carries it), and no top or right spines.
  Axes are 0.6 pt dark grey. Light y-gridlines (0.4 pt, `#E5E5E5`) only where reading values matters.
- **Palette** (colour-blind safe):
  - our strategy: **orange `#F26B21`**;
  - comparison series: black `#000000`, dark grey `#555555`, mid grey `#9A9A9A`;
  - **blue `#2C6FBB` only when a third category is genuinely needed**, such as source-class bands;
  - IS vs OOS: **solid vs dashed**, not different hues;
  - seed bands: a 15–20% alpha fill of the line colour.
- **Direct labels** at line ends beat legends (P6 puts the Sharpe in the legend label, which is a good
  trick when a legend is unavoidable).
- Panel letters **(a)**, **(b)**, **(c)** in bold at the top left of each panel, matching the subcaptions.
- Reference lines:
  - zero line: 0.6 pt black;
  - the **1 s baseline: dotted vertical line**, labelled "expected latency: licensed feed";
  - break-evens: open-circle markers labelled with the value.

### Captions: a takeaway sentence plus a source line

Each caption has four parts, in this order:

1. the bold label;
2. **one takeaway sentence**;
3. what is plotted, the sample and the units, plus the honesty label if the float shows CV-strategy numbers;
4. `Source:` followed by the files and data (e.g. `Source: Polymarket tapes; results/tier0/latency_sweep.json`).

Example:

> **Figure 2. Each second of feed delay costs the edge; at the pre-registered timing it is gone by about 1 s.**
> Net $/day (a) and annualised Sharpe (b) against feed delay V (log scale), in sample (solid) and burned
> out of sample (dashed), for the calibrated (post hoc) and pre-registered 2.0 s stamp-lag readings; bands
> span 20 seeds. Simulated at an assumed feed latency (licensed feed not purchased); parameters measured.
> Source: Polymarket public tapes; `results/tier0/latency_sweep.json`.

Table captions use the same pattern above the table, with "Notes:" and "Source:" in 11 pt below it.

---

## (c) The track blueprint mapped to our sections, with page budgets

The title block and abstract take about 0.4 p of page 1. That space has to come from somewhere, so the
track's suggested budgets (which sum to 5.0) are tightened slightly. **The hard limit is that the last
line of §8 sits on page 5.** References and the appendix start on a new page after that.

| § | Section (track blueprint name) | Track budget | Our budget | Floats on main pages |
|---|---|---|---|---|
| | Title block, abstract, JEL, keywords | n/a | 0.40 | none |
| 1 | Summary | 0.25 | 0.25 | Key-findings box (counts as text) |
| 2 | Economic hypothesis | 0.5 | 0.45 | Eq. (2) Markov point leverage |
| 3 | Data & universe | 0.5 | 0.40 | Footnotes for sources |
| 4 | Methodology | 1.0 | 0.90 | Eq. (1) fee, Eq. (3) latency budget |
| 5 | Results | 1.25 | 1.30 | Table 1 (tests), Table 2 (v2 IS/OOS), Table 3 (1 s baseline), Fig. 1 (equity curve), Fig. 2 (centrepiece) |
| 6 | Risk management | 0.5 | 0.45 | none (optional half-width table) |
| 7 | Liquidity & capacity | 0.5 | 0.45 | none |
| 8 | Limitations & next steps | 0.5 | 0.45 | none |
| | **Total** | 5.0 | **5.05 → trim to 5.0** | |

Rough capacity at 11 pt Source Sans 3 on a 6.5 × 9 in text block: about 700 words per page of pure text.
Two full-width figures (about 2.8–3.2 in tall each) and three 11 pt tables use about 2.1 pages. That leaves
about **2,000–2,200 words of running text**, against 2,976 in the current `docs/NOTE.md`, so cut hard.
Fig. 2 must sit on page 3 or 4, near its first reference.

### Every checklist item placed in a section (REQUIREMENTS.md item → where → evidence)

| Item | Requirement | Section | Evidence and source of the numbers |
|---|---|---|---|
| 2, 4 | ≤ 5 pages incl. figures and tables; appendix may go unread | whole note | build check (rule 1). Nothing scored only in the appendix |
| 3 | 11 pt everywhere, standard margins | whole note | rule 2 |
| 5, 19–21 | Hypothesis before results, committed first | §2 | `HYPOTHESIS.md` (commit `7232986`), `HYPOTHESIS_V2.md`; H6 box quoted in the track's template form (universe / behaviour / horizon / counterparty / persistence / prediction / falsifier) |
| 6, 7 | IS and OOS separate, net of costs; annualised return, vol, Sharpe, max DD, turnover, equity curve, for both | §5 Table 2, Fig. 1 | `results/v2/causal.json`, `results/v2/note_metrics.json`, `results/figures/` (equity curve redrawn in house style) |
| 8 | Risk and capacity sections | §6, §7 | `docs/RISK.md`, `research/financials/FINANCIALS.md` |
| 9, 43 | Variant count and failures | §5 (failures in Table 1) and §8 (count) | 3,410 variants plus tier-0 scenarios (as in `docs/NOTE.md` §7). Failures: H1, H2, H5, v1 OOS −$36k, fees ×2 OOS negative, U2 OOS fail, maker v1 blind fail, table tennis untestable/illiquid, financials negative OOS after fixed costs |
| 10 | 8-section blueprint | §1–§8 | this table |
| 13, 46 | One command reproduces the numbers | page-1 footnote, §3 last line | `bash reproduce.sh`. All note numbers come from JSON through `build_paper.py` |
| 16, 37 | Cite every source; extend and say what is new | §2 "What is new", §3 sources, References | Polymarket APIs, Kalshi, ESPN, WTA API, Ken French library, OpenTTGames, TrackNet, BlurBall, WASB-SBDT, plus P1–P4, P6, Brown (2012), Klaassen & Magnus (2001), Bailey & López de Prado (2014) |
| 17 | Disclose pre-existing components | §3 (one sentence) or a References note | detector weights and datasets are third-party and cited |
| 22 | Market scope | §3 | one sentence: Polymarket binary contracts, public order book, free tick data |
| 24–27 | Holdout rule, evaluated once, report OOS and every peek | §3 (holdout definition), §5 (peek paragraph) | `results/oos_peeks.log` (65 lines at time of writing; **count at build time**). Say which looks were blind and which were burned |
| 28 | Tune only in sample, walk-forward | §4 Validation | monthly walk-forward; purge note |
| 29 | No lookahead | §4 Execution | the D9 fix, wallets qualify on past months, fee in force |
| 30–31 | Costs in bps with justification; costs doubled | §4 Costs plus Eq. (1); §5 Table 2 rows | fee = rate·q(1−q); 120 / 179 bps IS/OOS; `results/v2/cost_stress.json`. **State plainly that OOS goes negative when fees double** |
| 32 | Survivorship, corporate actions, missing data | §3 | lifetime-volume filter caveat; 50/50 settlements; truncated tapes |
| 33–34 | p-hacking guards, plateau, deflated Sharpe | §5 "Sharpe above 3" paragraph | `results/rigor/rigor.json` (PBO, DSR, bootstrap) |
| 35 | Skew and worst month next to Sharpe; explain Sharpe > 3 | Table 2 rows, §5 paragraph | `results/v2/note_metrics.json` |
| 36 | Regime / period breakdown | Table 2 row group "By month" plus §2 venue-regime sentence | months positive 7/7 IS, 2/3 OOS; edge per share by fee and delay regime |
| 40 | Factor regression | §6 | `results/v2/factor_regression.json` (alpha t, betas, R²) |
| 41 | Capacity in $, ADV fraction, costs-doubled sensitivity | §7 | `research/financials/FINANCIALS.md`, stale depth per point, ~$100k |
| 42 | Limits, de-risking rules, tail/regime | §6 | `docs/RISK.md`, `engine/risk/` kill switches |
| 44 | No real money | page-1 footnote, §6 | TERMS 5.3 |
| 45 | Licences / ToS | §6 Settlement & legal | courtsiding vs ticket terms, licensed data, venue geo-restrictions |
| Honesty | CV label, live session, forward test | §5 Table 3, Fig. 2, §8 | `results/live/summary.json`, `results/v2/forward.json` when present, otherwise the literal word "pending" |

### Section-by-section content contract (the evidence ladder in five pages)

1. **Summary.** Thesis sentence (from STORY), then the key-findings box.
2. **Economic hypothesis.** The tennis information tiers (venue/official ≤ 0.15 s → licensed feed → apps →
   streams → score widgets). Who is on the other side: slower takers. Why it persists: physical latency, data
   licensing, and the venue's 1 s order delay. Eq. (2). H6 in template form. What is new, with citations
   P1, P2, P3, Brown (2012) and P4.
3. **Data & universe.** Instruments, dates, the 80/20 holdout and the forward window, sources as
   footnotes, and data problems.
4. **Methodology.** Fast-tier identification, v2 sizing, caps and execution (filled at fast-tier fills
   = the opportunity at their speed). CV pipeline in one paragraph: held-out table tennis
   (`results/tracking/summary.json`), `results/spin/`, `results/engine/`, and
   `results/webrtc/latency.json` only if it exists. The latency counterfactual and Eq. (3). Costs and
   Eq. (1). Validation.
5. **Results.** Run IS before OOS throughout:
   - Table 1: the test ladder, including what failed;
   - Table 2: v2 IS | OOS with all six metrics, plus skew, worst month, costs doubled, ½ / 1 tick worse;
   - Fig. 1: the equity curve;
   - Table 3: the CV strategy at the simulated 1 s licensed-feed baseline;
   - Fig. 2: the signal-decay centrepiece;
   - the "Sharpe above 3" paragraph;
   - blind tests (U2 fail), the forward test slot, and the peek paragraph.
6. **Risk management.** Limits, de-risking rules (set in advance), venue-rule risk, crowding,
   tail/regime, factor regression, settlement and legal, real money none.
7. **Liquidity & capacity.** Depth and impact, capacity in $ with the costs-doubled effect, the latency
   ladder of real sources (book leads the stamp by 1.2 s; ESPN 28 s; PM sports feed 30 s; fastest public
   stream 12.2 s, preliminary, exclude any YouTube-derived figure; sportsbook streams 4–8 s), and financials
   after fixed costs (negative OOS, reported).
8. **Limitations & next steps.** The unmeasured stamp lag is the key uncertainty. Say how to measure it:
   one live session with a licensed feed. Licensing an official low-latency feed (Polymarket buys official
   data from Genius Sports) turns the simulation into deployment. A faster feed moves us left on the curve.
   Venue partnerships. Table tennis is illiquid. What could break it.

### Table 3 (main results table for the CV strategy): exact cells

All cells come from `results/tier0/latency_sweep.json` → `video_own120.<reading>["1"].<IS|burned_OOS>`, at
V = 1.0 s. I checked the values on October 3; the build reads them live:

| Reading at V = 1.0 s | Period | $/day | ¢/share [95% CI] | Sharpe (ann.) | Break-even V |
|---|---|---|---|---|---|
| Calibrated stamp lag 3.14 s (`tournament_lagcal`; calibrated, post hoc) | IS | +94.35 | +1.113 | 11.95 | 2.23 s |
| | OOS | +56.59 | +0.655 | 8.85 | 2.14 s |
| Pre-registered 2.0 s (`tournament`) | IS | +14.78 | +0.401 | 2.15 | 1.09 s |
| | OOS | +4.35 | **−0.383** | 0.34 | 1.01 s |

- The break-evens are `breakeven_video_delay.<reading>.<period>.breakeven_V_s_seed_mean_curve`. CIs are in
  `net_c_per_share_ci95` and `usd_per_day_seed_ci95`.
- **Watch:** for the 2.0 s reading, OOS $/day is positive but ¢/share is negative. Print both and say so in
  one clause. Do not show only the positive one.
- **Break-even about 1.0–1.1 s applies to the pre-registered 2.0 s reading.** The calibrated reading breaks
  even at about 2.1–2.2 s. Do not mix them up.
- The lag-1.0 stress (`tournament_lag1`, negative: IS −$6.27/day, OOS −$11.20/day) goes in the appendix
  (Table A1), with a pointer in §5.
- At 11 pt this table must keep at most 5 numeric columns. If it is too wide, move CIs to a second line in
  each cell or drop "Break-even" into the caption.
- Caption label (mandatory): "Simulated at a 1 s licensed-feed baseline: assumed feed latency (licensed
  feed not purchased); parameters measured."

### Equations (numbered, used in the text)

- (1) **Fee.** Fee per share = r·q(1−q). In bps of notional this is 10⁴·r·(1−q), which is 250 bps at
  q = 0.5, r = 5%.
- (2) **Markov point leverage.** L_k = P(win | point k won) − P(win | point k lost), from the exact
  point-level chain (`src/markov.py`; Klaassen & Magnus 2001). The mean move is 5.7%.
- (3) **Latency budget.** t_call = t_bounce − ℓ_CV + V + 0.020 s. The order arrives at
  t_call + δ_net + 0.002 s + 1 s (the venue delay). The trade is profitable only if it arrives before
  t_reprice, with t_reprice − t_bounce = R + stamp lag (from the `model.video` string in the JSON).

---

## (d) Ten rules the build agent must follow

1. **Five-page hard check, automated.** Put `\label{lastmain}` at the end of §8. `build_paper.py` fails if
   `\pageref{lastmain}` > 5. References start with `\clearpage`. Appendix floats are numbered A1, A2… (use
   `\renewcommand\thefigure{A\arabic{figure}}` and the same for tables after `\appendix`). Nothing a judge
   needs for scoring lives only in the appendix.
2. **11 pt everywhere on pages 1–5, verified.** After compiling, open the PDF with pymupdf and fail if any
   text span on pages 1–5 is below 10.9 pt. Exempt only spans flagged superscript (footnote markers,
   exponents) and math sub/superscripts. This covers captions, table cells, notes, footnotes, the abstract,
   the header, the footer and figure text. Check margins: no text bbox outside 72 pt from any edge, except
   header and footer.
3. **No hand-typed numbers.** Every number in the text, tables and captions comes from JSON. Generate
   `\newcommand` macros (e.g. `\vTwoOOSSharpe`) into `docs/paper/numbers.tex`. The build fails on a missing
   key. Pending slots read `results/live/summary.json` and `results/v2/forward.json` when present and
   otherwise print "pending". `scripts/forward_test.py` is never run.
4. **Honesty labels are literal and attached.** Every table, figure and sentence with CV-strategy numbers
   carries "assumed feed latency (licensed feed not purchased); parameters measured", or "simulated at a 1 s
   licensed-feed baseline" plus that label in the caption. v2 numbers say "at the fast tier's own fills".
   Never write that we have a feed, footage, a camera, or live ATP/WTA data. Real money: none. Grep the
   built PDF text for forbidden claims ("our feed", "our camera", "licensed feed we", "received video") and
   fail if any appear.
5. **Captions do the work.** Bold "Figure n." / "Table n.", one takeaway sentence, then what is plotted with
   units and sample, then the honesty label if needed, then "Source: …". Table captions go above and figure
   captions below. Notes and source sit under tables, all at 11 pt.
6. **Journal tables.** Use `booktabs` (`\toprule`, `\midrule`, `\cmidrule`, `\bottomrule`) and no vertical
   rules. Use `siunitx` `S` columns with `table-format` and true minus signs. Put IS and OOS side by side,
   CIs in brackets, and bold row groups ("Full period", "By month", "Costs stressed"). Use at most 5 numeric
   columns at 11 pt: use fewer columns, never a smaller font, and never `\resizebox`.
7. **Journal figures.** These are made by `scripts/paper_figures.py` as vector PDF at final size with
   Source Sans 3 at 11 pt, on white, with thin axes and no top or right spines. Orange is ours, black and
   greys are others, and blue appears only where needed. Show IS as solid lines and OOS as dashed. Mark
   panels (a)(b)(c). Draw the dotted 1 s baseline line, shaded source-class bands, and break-even markers.
   Fig. 2 has two panels: (a) $/day and Sharpe vs V, on a log-x axis from 0.05 to 60 s; (b) market-side
   decay from `results/decay/decay.json`, comparing the fast tier with everyone else.
8. **Order and placement.** Present the hypothesis before the results, IS before OOS, and each failure next
   to the success it qualifies. Use `[t]` or `[tb]` floats placed after their first reference, on the same
   page or the next. No float-only pages and no `[H]` floats in the main text. Every Sharpe has skew, worst
   month and max DD in the same table or sentence, plus the "Sharpe above 3" explanation in §5.
9. **House style, not a house brand.** Use Oswald for the title and wordmark, Source Sans 3 for the body and
   headings, and Fira Math for math. Put the orange-over-black double rule and a centred page number on every
   page, and "COURTSIDE" at top right on pages 2+. Never use the AlgoGators logo or call this an AlgoGators
   publication. Commit the fonts with `OFL.txt`. tectonic must build from `docs/paper/` with no system
   fonts. Fall back to `scripts/make_pdf.py` (HTML→Chrome) only after real debugging fails within 20 min.
10. **Look at it before you ship.** Render every page to PNG at about 110 dpi with pymupdf and inspect it.
    Check for:
    - zero overfull boxes > 1 pt in the log;
    - no widows or orphans (`\widowpenalty=10000`, `\clubpenalty=10000`);
    - no section heading stranded at a page foot (`\needspace`);
    - balanced whitespace, with the title block no taller than 1.9 in;
    - links dark slate, not boxed.

    Compare the pages with `docs/paper/reference/*.png` for the house look and with P2 / P5 for rigour.
    Then update `docs/COMPLIANCE.md` with the new section and page references.

---

## Appendix to this guide: suggested preamble skeleton (adapt; not tested here)

```latex
\documentclass[11pt,letterpaper]{article}
\usepackage[margin=1in,footskip=0.45in,headheight=14pt]{geometry}
\usepackage{fontspec,unicode-math}
\setmainfont{SourceSans3}[Path=fonts/, Extension=.ttf, UprightFont=*-Regular, BoldFont=*-Semibold,
  ItalicFont=*-It, BoldItalicFont=*-SemiboldIt]          % adobe-fonts/source-sans TTF/ names
\newfontfamily\display{Oswald}[Path=fonts/, Extension=.ttf, UprightFont=*-Light, BoldFont=*-Regular]
\setmathfont{FiraMath-Regular.otf}[Path=fonts/]
\usepackage{microtype,booktabs,siunitx,graphicx,xcolor,tikz,fancyhdr,titlesec,needspace}
\usepackage[labelfont=bf,font=normalsize,labelsep=period]{caption}
\usepackage{subcaption}
\usepackage[authoryear,round]{natbib}
\definecolor{gator}{HTML}{F26B21}\definecolor{linkslate}{HTML}{1F3A5F}
\usepackage[colorlinks,linkcolor=linkslate,citecolor=linkslate,urlcolor=linkslate]{hyperref}
\renewcommand\footnotesize{\normalsize}                   % 11 pt footnotes (track rule)
\sisetup{group-minimum-digits=4, table-number-alignment=center}
\titleformat{\section}{\fontsize{14}{17}\selectfont}{\thesection}{1.2em}{}
\widowpenalty=10000 \clubpenalty=10000
\pagestyle{fancy}\fancyhf{}\renewcommand{\headrulewidth}{0pt}
\fancyhead[R]{\ifnum\value{page}>1 {\display\fontsize{11}{13}\selectfont COURTSIDE}\fi}
\fancyfoot[C]{\begin{tikzpicture}
  \fill[gator] (0,0.10) rectangle (\textwidth,0.17);      % orange, ~2 pt
  \fill[black] (0,0) rectangle (\textwidth,0.035);        % black,  ~1 pt
  \end{tikzpicture}\\[2pt]\fontsize{11}{13}\selectfont\thepage}
\fancypagestyle{plain}{}  % page 1 uses the same footer and no wordmark
```
