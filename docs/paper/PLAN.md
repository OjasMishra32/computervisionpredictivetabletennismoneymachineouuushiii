# COURTSIDE paper: build plan

This file is the blueprint for the LaTeX build. It fixes four things: the exact five-page layout, every float,
the appendix, and the source of every number. It sits on top of `docs/paper/STYLE_GUIDE.md` (commit `e1b5272`),
which holds the house style, the preamble skeleton and the ten build rules. This plan does not repeat them; where
the two differ, **this plan wins on layout and content, and the style guide wins on typography**. Both rank below
the track rules (`research/compliance/REQUIREMENTS.md`) and the honesty rules (§13).

Checked against the repo on 2026-10-03 (HEAD `1ccf1c9`). Values quoted below are for orientation only. The build
reads every number live from the files named in §12 and fails on a missing key.

---

## 0. Decisions this plan makes (read first)

1. **Four main-text figures, not five or six.** Each one is a dense multi-panel figure, and together they carry
   all six requested contents (information tiers, speed→Sharpe curve, fast tier vs others, decay within a point,
   v2 equity with costs doubled, CV evidence with the WebRTC latency bar, risk/capacity, real-match replay). The
   arithmetic in §2 shows why. At 11 pt everywhere, with three tables and the required sections, five or six
   separate figures leave fewer than 700 words of prose. The replay becomes panel 3(d), and the size curve and
   waterfall stay together in Fig. 4. If the first build leaves at least 14 free lines on page 5, promote the
   replay to its own Fig. 5 (§8, grow ladder G1).
2. **Order follows the evidence ladder:** who is fast and what they earn (Fig. 2a), what that is worth at their
   fills (Table 1, Fig. 2b), what our CV can do (Fig. 1b), what each second of feed latency is worth (Fig. 3,
   Table 2), a real-book replay (Fig. 3d), then failures (Table 3), risk, capacity and limitations.
3. **Hypothesis before results, physically as well as logically.** Nothing on pages 1–2 shows strategy P&L.
   Fig. 1 on page 2 shows latencies and held-out CV call accuracy, which are method inputs. The first P&L float
   is Fig. 2, at the top of page 3, after H6 (page 2).
4. **The main results table (Table 2) puts the two stamp-lag readings side by side at V = 1.0 s**, IS and OOS, as
   the team decided. The calibrated reading is labelled "calibrated, post hoc"; the 2.0 s reading is labelled
   "pre-registered". The lag-1.0 stress gets one sentence in the Table 2 notes and its full row in Table A1.
5. **The replay is reported as a failure next to the success it qualifies.** At V = 1 s on the nine matches
   recorded live on 2026-10-03, every one of its 36 cells loses money marked to market, including stamp lag 3 s.
   It is a consistency check, not new evidence (protocol `research/replay/PROTOCOL.md`), but it goes in Fig. 3(d)
   and Table 3. Leaving it out would be a disqualification-level omission.
6. **Every number comes from JSON through macros** (style-guide rule 3). Policy constants that live only in prose
   or code are copied into `results/paper/policy.json` with file:line provenance (§12.13). They are never typed
   into the `.tex`.

---

## 1. Files and pipeline

| Path | Role |
|---|---|
| `docs/paper/main.tex` | the paper: `\usepackage{courtside}`, `\input{numbers.tex}`, sections, `\label{lastmain}` at the end of §8, `\clearpage` then References, then `\appendix` |
| `docs/paper/courtside.sty` | house style (style guide §(b) and its preamble skeleton): fonts, footer double rule, wordmark, captions, titlesec, natbib |
| `docs/paper/numbers.tex` | **generated** by `scripts/build_paper.py`; one `\csname` entry per key (below) |
| `docs/paper/refs.bib` | natbib author-year bibliography (§9.3) |
| `docs/paper/fonts/` | Oswald-Light/Regular.ttf + `OFL.txt`; SourceSans3-{Regular,It,Semibold,SemiboldIt}.ttf + `LICENSE.md`; FiraMath-Regular.otf + its OFL |
| `scripts/paper_figures.py` | writes `results/paper/fig{1..4}_*.pdf` and `results/paper/figA*_*.pdf` (vector, final size, 11 pt Source Sans 3) |
| `scripts/build_paper.py` | reads JSON → `results/paper/numbers.json` + `docs/paper/numbers.tex`; runs `paper_figures.py`; runs `tectonic`; runs the checks in §15; copies the PDF to `docs/NOTE.pdf`; regenerates `docs/NOTE.md` as a short companion (abstract, key findings, Table 2 core, link to the PDF) from the same numbers |
| `results/paper/` | numbers.json, policy.json, variants.json, peeks.json, figures, `pages/p{1..N}.png` renders, `checks.json` |
| `scripts/make_pdf.py`, `docs/NOTE.html` | fallback only (HTML→Chrome), used only if tectonic still fails after 20 min of debugging |

**Macro scheme.** Use dotted keys with a checking accessor, so that a missing key stops the build:

```latex
\newcommand\V[1]{\ifcsname cs@#1\endcsname\csname cs@#1\endcsname\else\errmessage{COURTSIDE: missing number #1}\fi}
% numbers.tex (generated):  \expandafter\def\csname cs@v2.oos.c\endcsname{+0.60}
```

In the text: `\V{v2.oos.c}`. Format in Python, never in TeX. Use true minus signs (U+2212) and thin-spaced
thousands ("13,084"). Use a leading "+" on signed P&L. Format the stored floats with `f"{x:.1f}"`, which gives
the team's quoted 11.9 / 8.8 / 2.1 / 0.3. Do not re-round two-decimal strings half-up.

---

## 2. Page arithmetic: why the budgets are what they are

* **Text block:** 6.5 × 9.0 in (letter paper, 1 in margins). The 11 pt Source Sans 3 body has 13.6 pt leading, so
  648 pt / 13.6 = 47.6 lines; we plan for **47 lines a page, 235 in total**. A full-width line holds about 90
  characters, or about **14 words**.
* **Float costs, in lines, including caption and float separation:**

| Element | Size | Lines |
|---|---|---|
| Title block (p. 1, no cover page) | ≤ 1.55 in | 8.0 |
| Abstract (≤ 140 words) + JEL / keywords | | 10.5 |
| First-page unmarked footnote (11 pt) | 3 lines | 3.3 |
| 8 section headings (14 pt, 8 pt before, 3 pt after) | 8 × 2.06 | 16.5 |
| §1 key-findings box (5 bullets, orange rules) | | 9.0 |
| 3 numbered display equations | 3 × 1.9 | 5.7 |
| **Fig. 1** (2 panels, 6.5 × 2.05 in) + 3-line caption | | 14.8 |
| **Fig. 2** (2 panels, 6.5 × 1.85 in) + 2.5-line caption | | 13.2 |
| **Fig. 3** (2 × 2 panels, 6.5 × 3.3 in) + 4-line caption | | 22.5 |
| **Fig. 4** (2 panels, 6.5 × 1.85 in) + 2.5-line caption | | 13.2 |
| **Table 1** (v2 IS / OOS, 12 rows + group label) | | 20.5 |
| **Table 2** (CV at 1 s, 7 rows × 4 numeric columns) | | 15.5 |
| **Table 3** (failures and pending, 8 rows) | | 15.0 |
| H6 box (template quote, ≤ 60 words) | | 4.5 |
| **Sum of fixed elements, floats and the H6 box** | | **172.2** |
| Slack for float-placement losses | | 3.0 |
| **Running prose available** | 235 − 175.2 | **≈ 59.8 lines ≈ 835 words** |

* **Prose budget: 835 words in total** (§4 gives the per-section split), plus the H6 box. With it the plan
  totals about 231 of 235 lines, about 4 lines to spare. There are also about 140 words of abstract, about
  120 words in the box and about 450 words in captions and table notes. The paper is about 1,600 words, the
  density of the AQR / Man notes in the style guide (P5, P7).
* **Why not 5–6 figures?** Each extra two-panel figure costs 13 lines, about 185 words. Six figures leave
  fewer than 700 words of prose for eight sections, which is too few for the Economic Foundation and Risk
  criteria. Four dense figures with eleven panels in all carry the same content.

---

## 3. Page-by-page layout (targets; tectonic decides the final float positions)

Float placement: Fig. 1 `[t]` on page 2; Fig. 2 `[t]` on page 3; Table 1 `[b]` on page 3; Fig. 3 `[t]` on page 4;
Table 2 `[b]` on page 4; Table 3 `[t]` on page 5; Fig. 4 `[b]` on page 5. No `[H]`, no float-only pages, and each
float on the same page as its first reference or the next one. Prose flows around the floats. Section prose
needs, in lines at 14 words a line: §1 2.0 · §2 12.9 · §3 6.1 · §4 12.1 · §5 9.6 · §6 7.5 · §7 4.3 · §8 5.4 = 59.9.

| Page | Floats and fixed items (lines) | Prose that lands here (lines) | Total |
|---|---|---|---|
| **1** | Title block 8.0 · Abstract + JEL/keywords 10.5 · §1 and §2 headings 4.2 · key-findings box 9.0 · first-page footnote 3.3 → 35.0 | thesis 2.0 · §2 ¶1 + Eq. (2) reference + start of ¶2 10.0 → 12.0 | 47.0 |
| **2** | **Fig. 1** [t] 14.8 · H6 box 4.5 · Eq. (2) 1.9 · §3 and §4 headings 4.2 · Eq. (1) 1.9 → 27.3 | rest of §2 (incl. ¶3, what is new) 2.9 · §3 6.1 · §4 first 10.5 → 19.5 | 46.8 |
| **3** | **Fig. 2** [t] 13.2 · Eq. (3) 1.9 · §5 heading 2.1 · **Table 1** [b] 20.5 → 37.7 | end of §4 1.6 · §5 ¶1 + start of "Sharpe > 3" 7.0 → 8.6 | 46.3 |
| **4** | **Fig. 3** [t] 22.5 · **Table 2** [b] 15.5 · §6 heading 2.1 → 40.1 | rest of §5 (1 s baseline, replay, Table 3 lead-in) 2.6 · start of §6 4.0 → 6.6 | 46.7 |
| **5** | **Table 3** [t] 15.0 · **Fig. 4** [b] 13.2 · §7 and §8 headings 4.2 → 32.4 | rest of §6 3.5 · §7 4.3 · §8 5.4 → 13.2; `\label{lastmain}` | 45.6 |
| | | | **232.4 / 235** |

Table 3 sits at the top of page 5, after §6 has started on page 4. That is legal: it is referenced at the end of §5
and floats to the next page. If the first build overflows page 5, apply the trim ladder (§8) in order. The hard
check is `\pageref{lastmain} ≤ 5`.

---

## 4. Section-by-section content contract

Running-prose budgets (words) exclude floats, captions, equations, the key-findings box and the H6 box:
**§1 25 · §2 180 · §3 85 · §4 170 · §5 135 · §6 105 · §7 60 · §8 75 = 835**. Macro keys are in ⟨⟩ and are
defined in §12.

### Title block (p. 1)

* Title, in Oswald Light at 24 pt on two lines: **COURTSIDE: Pricing the Value of Speed in In-Play Tennis
  Prediction Markets**
* Authors line: `[Author names — team to fill]` · University of Florida · `[emails]`
* "Gator Quant Hacks 2026 · Systematic Trading Track · University of Florida"
* "October 4, 2026"
* No logo and no AlgoGators name. The "COURTSIDE" wordmark goes top right from page 2 only.

### Abstract (≤ 140 words; draft, numbers as macros)

> We study who profits from speed in Polymarket's in-play tennis moneylines, using public order-book tapes for
> ⟨univ.matches⟩ matches (⟨univ.volume⟩ traded). A walk-forward fast tier of wallets trading within 3 s of a score
> move earns after fees in ⟨ft.months.is⟩ in-sample and ⟨ft.months.oos⟩ held-out months. Every other taker
> loses, and copying the same trades 3 s later loses. At the fast tier's own fills a frozen book earns
> ⟨v2.oos.c⟩¢ per share out of sample (Sharpe ⟨v2.oos.sr⟩), but it turns negative when fees double. We then price
> the speed a computer-vision trader needs. Simulated at a 1 s licensed-feed baseline (assumed feed latency;
> licensed feed not purchased; parameters measured), it earns ⟨cv.cal.oos.usd⟩/day out of sample under a post hoc
> calibrated stamp lag, and ⟨cv.pre.oos.usd⟩/day under the pre-registered one, which breaks even at
> ⟨cv.pre.be.oos⟩ s of feed delay. Real money: none.

Below the abstract: `JEL classification: G14, G12, C58` · `Keywords: prediction markets; latency arbitrage;
in-play betting; tennis; computer vision; market microstructure` (one line if it fits, two if not).

### First-page footnote (unmarked, 11 pt, 3 lines)

"Reproduce: `bash reproduce.sh`, then `python scripts/build_paper.py`; code and data scripts:
github.com/OjasMishra32/computervisionpredictivetabletennismoneymachineouuushiii. Real money: none; no funded
account was connected to any event activity (Participant Terms 5.3). CV-strategy results: assumed feed latency
(licensed feed not purchased); parameters measured. We hold no licensed feed, no match footage and no camera at
any court."

### §1 Summary (25 words + box)

* Thesis sentence, from the brief: "In-play tennis prediction markets are priced by whoever learns the point
  first; we measure who that is, what they earn, and what each second of speed is worth."
* **Key-findings box** (thin orange rule above and below; five bold run-in bullets; ≤ 125 words in total):
  1. **Strategy.** Call the point with computer vision before the ball lands, and take the stale Polymarket quote
     inside the venue's ⟨venue.delay⟩ s order delay. Simulated at a 1 s licensed-feed baseline (label).
  2. **Edge.** The book reprices ⟨lat.book_vs_stamp⟩ s before the official stamp. The fast tier earns
     ⟨ft.c.is⟩¢ / ⟨ft.c.oos⟩¢ per share after fees (IS / OOS) in every month, while other takers lose
     ⟨oth.c.is⟩¢ / ⟨oth.c.oos⟩¢.
  3. **Headline OOS.** At fast-tier fills: ⟨v2.oos.c⟩¢ [⟨v2.oos.ci⟩], Sharpe ⟨v2.oos.sr⟩, max DD ⟨v2.oos.dd⟩. At
     the 1 s baseline: ⟨cv.cal.oos.usd⟩/day (Sharpe ⟨cv.cal.oos.sr⟩, calibrated, post hoc) against
     ⟨cv.pre.oos.usd⟩/day (Sharpe ⟨cv.pre.oos.sr⟩, pre-registered).
  4. **Speed.** Break-even feed delay is ⟨cv.pre.be.oos⟩–⟨cv.pre.be.is⟩ s (pre-registered) or
     ⟨cv.cal.be.oos⟩–⟨cv.cal.be.is⟩ s (calibrated). Public streams (≥ ⟨lat.webrtc_public⟩ s) and score feeds
     lose.
  5. **What failed.** Fees ×2 OOS (⟨v2.oos.fx2.c⟩¢), the blind unseen-market test, the maker and tier-0 v3 blind
     tests, the live-book replay (⟨rp.v1l2.c⟩¢ at 1 s), table tennis, and OOS net of a central feed licence
     (⟨fin.v2.oos.net_central⟩/day). Real money: none.

### §2 Economic hypothesis (180 words + Eq. 2 + H6 box)

* **¶1, tiers (≈ 75 words, p. 1).** Win probability is a known function of the score. Eq. (2) gives point
  leverage $L_k$: the mean |L| is ⟨markov.lev⟩ over ⟨markov.points⟩ points in a simulated ATP best-of-3
  (Klaassen & Magnus 2001). So each point moves fair value by a known amount at a known instant. The information
  reaches traders in tiers (Fig. 1a):
  * in-venue tracking at the bounce;
  * the umpire's official stamp, an unmeasured 1–3 s later;
  * licensed betting video, 0.5–8 s by vendor statement;
  * public streams, ≥ ⟨lat.webrtc_public⟩ s;
  * score feeds, ⟨lat.espn⟩–⟨lat.wta⟩ s behind the book.

  The book reprices a median ⟨lat.book_vs_stamp⟩ s *before* the official stamp (n = ⟨lat.n_points⟩).
* **H6 box** (track template, in a quote frame; ≤ 60 words). Use the wording of `HYPOTHESIS.md` H6, recast into the
  track's template: universe / behaviour / horizon / counterparty / persistence / prediction / falsifier. Then
  give the trail: "H1–H4 committed before any result (commit ⟨prereg.hyp.commit⟩, ⟨prereg.hyp.time⟩); H6 frozen
  before the OOS; v2 in `HYPOTHESIS_V2.md`; every change in `DEVIATIONS.md`."
* **¶2, counterparty and persistence (≈ 60 words).** The other side is slower takers acting on an older tier.
  The edge is a *structural/institutional constraint*, in the track's terms, not a risk premium: physics,
  data-licensing and the venue's 1 s taker hold. It responds to that structure as theory predicts: v2's edge per
  share is ⟨v2.reg.3s0⟩ / ⟨v2.reg.3s3⟩ / ⟨v2.reg.1s3⟩ / ⟨v2.reg.1s5⟩¢ across the 3 s/0 %, 3 s/3 %, 1 s/3 % and
  1 s/5 % delay/fee regimes. The fast tier grew from ⟨ft.wallets.first⟩ to ⟨ft.wallets.last⟩ wallets, and its edge
  shrank ⟨ft.slope⟩¢ a month (t = ⟨ft.slope.t⟩) while staying positive. This is the regime breakdown (item 36).
* **¶3, what is new (≈ 45 words).** Latency races in equities (\citet{budish2015}, \citet{aquilina2022}) and
  in-play mispricing and courtsiding (\citet{croxson2014}, \citet{brown2012}, \citet{brown2014}) are known. We add
  three things:
  * a walk-forward, wallet-level identification of the latency tier from public on-chain tapes;
  * a timing of every public source against the official point clock;
  * a price, in $/day and Sharpe, on each second of feed latency for a CV trader.

### §3 Data & universe (85 words)

* **Instruments.** ⟨univ.matches⟩ resolved ATP/WTA/Challenger singles moneylines with ≥ ⟨univ.minvol⟩ lifetime
  volume, ⟨univ.first⟩–⟨univ.last⟩. These are binary contracts on a public order book with free tick data.
  Takers pay the spread actually traded.
* **Split.** In sample is the first 80 % of matches by start time. OOS is the last ⟨univ.oos⟩ matches from
  ⟨univ.oosstart⟩ (⟨univ.oos_vol⟩ of volume, ⟨univ.oos_time⟩ of calendar time; the 2-year option does not bind).
  The forward window runs from 2026-10-03 14:00 UTC.
* **Data problems.**
  * The lifetime-volume filter is a survivorship risk; the blind test on ⟨u2.markets⟩ smaller markets checks it.
  * ⟨data.offsetcap⟩ tapes may be truncated; they are kept, not filled.
  * ⟨data.nofee⟩ early matches have no published fee schedule and are charged 0 %, the venue's early regime.
  * ⟨data.res5050⟩ of matches settle 50/50; they are included.
  * Tape stamps are block times, a median ⟨data.blocklag⟩ s late (n = ⟨data.blocklag.n⟩).
* Sources are in footnote 2: the Polymarket Gamma, Data and CLOB APIs and sports websocket; ESPN and the WTA API
  (latency only); the Kalshi API; the Ken French library; OpenTTGames. All are cited in the References.

### §4 Methodology (170 words + Eq. 1 + Eq. 3)

* **Fast tier and v2 (≈ 60 words).**
  * The detector fires on a ≥ ⟨pol.det_c⟩¢ move in the 10 s VWAP against the prior 60 s.
  * Each month a wallet qualifies on past months only: ≥ ⟨pol.q_prints⟩ prints within 0–3 s, over ≥
    ⟨pol.q_matches⟩ matches, with t > ⟨pol.q_t⟩ on its 30 s markout.
  * v2 copies qualifying prints in 0–3 s, sized ∝ 1/√(q(1−q)), capped at ⟨risk.order_usd⟩ per order and
    ⟨risk.netcap⟩ shares net per match, and holds to resolution.
  * **It fills at the fast tier's own print prices: the opportunity at their speed, not our execution.** Of v2's
    backtest dollars, ⟨decay.sameblock.share⟩ sit in the detection block itself, which a reacting bot cannot reach.
* **CV strategy (≈ 60 words).**
  * Our tracker calls the point before contact (Fig. 1b).
  * The simulated trader's order follows Eq. (3) and fills against the live recorded books (482 official points).
    The reprice timing, depth, network and fees are measured; the feed delay V and the stamp lag L are assumed.
  * V is swept from 0 to 60 s with 20 seeds per cell.
  * L is unmeasured, so we report two readings: the **pre-registered** L = ⟨cv.pre.lag⟩ s and the
    **calibrated, post hoc** L = ⟨cv.cal.lag⟩ s, inferred from fast-tier timing.
* **Costs (≈ 30 words).**
  * Eq. (1): each match's own taker fee. It averages ⟨v2.is.fee_bps⟩ / ⟨v2.oos.fee_bps⟩ bps of notional on v2's
    trades (IS / OOS), and ⟨fee.bps_q05⟩ bps at q = 0.5.
  * Spreads are paid as traded.
  * Stresses: +½ and +1 tick worse entry, fees ×2, and all costs ×2 (fee twice plus half a 1¢ spread,
    ≈ ⟨v2.is.hs_bps⟩ bps).
* **Validation (≈ 20 words).** Monthly walk-forward inside IS. No future data: the D9 onset fix, wallets qualify
  on past months, and the fee in force is used. Every OOS read is logged.

### §5 Results (135 words around the floats)

* **¶ on p. 3 (≈ 50 words).**
  * The fast tier beats other takers in every month, and copying it 3 s later loses (Fig. 2a).
  * At their fills, v2 makes the Table 1 numbers in both periods, with the equity curve in Fig. 2b.
  * Out of sample it is gone at +½ tick, and negative with fees doubled (⟨v2.oos.fx2.c⟩¢, ⟨v2.oos.fx2.mpos⟩
    months positive). In sample it survives both.
* **"Sharpe above 3" (≈ 50 words, p. 4).** We assumed a bug and found one: D9 onset labelling cut IS Sharpe from
  ⟨v2.onset.is.sr⟩ to ⟨v2.is.sr⟩. What remains is about ⟨v2.trades_per_day⟩ small, near-independent bets a day:
  * the implied same-day pairwise correlation is ⟨risk.corr_sameday⟩;
  * net exposure is capped per match;
  * deflated Sharpe ⟨rig.dsr.is⟩ IS at N = ⟨rig.N⟩, but ⟨rig.dsr.oos⟩ OOS, so 40 days cannot rule out luck;
  * the CV curve's Sharpe is a seed-mean ranking of a simulation and ignores model risk.
* **The 1 s baseline (≈ 25 words).** Fig. 3a–b and Table 2.
  * The two readings bracket the result.
  * Under the alternative stamp-noise timing reading the trader loses at every V (Table A1).
  * The replay on live-recorded books loses at every V and lag (Fig. 3d), because it calls every point rather
    than ≥ 4¢ jumps.
* **¶ on p. 5 (≈ 10 words + Table 3).** Every blind test of a tradable book failed; the mechanism held.
  Forward test and live session: ⟨fwd.status⟩ / ⟨live.status⟩. Peeks: "⟨peeks.n⟩ logged reads of held-out data
  (⟨peeks.blind⟩ blind first runs, ⟨peeks.nonblind⟩ non-blind reads of the burned window, ⟨peeks.desc⟩
  descriptive, ⟨peeks.audit⟩ audits/reproductions, ⟨peeks.live⟩ replays/live); rules changed after a look twice
  (v2, D9); full list Table A6." The peek sentence may sit in the Table 3 notes if it fits better.

### §6 Risk management (105 words; bold run-in bullets)

* **Limits.**
  * ⟨risk.order_usd⟩ per order, ⟨risk.netcap⟩ shares net per match, price zone ⟨risk.zone⟩.
  * Capital is 3× peak locked (⟨v2.is.cap⟩), or ⟨risk.cap_realised⟩ on realised locks.
  * Worst day: ⟨v2.is.worstday_usd⟩ IS, ⟨v2.oos.worstday_usd⟩ OOS.
* **De-risking, set in advance.**
  * Halve size if the trailing-30-day edge is below ⟨pol.trail_half⟩¢; stop at ≤ 0. Replayed on IS it never fires
    (minimum ⟨risk.trail_min⟩¢).
  * Stop at a ⟨pol.dd_stop⟩ drawdown.
  * Stop on any fee or delay change until the cost stress is re-run.
* **Kill switches, in code (`engine/risk/`).**
  * Daily stop ⟨risk.daily_stop⟩ (⟨risk.daily_stop_sigma⟩ σ of IS daily P&L).
  * Stale feed > ⟨risk.feed_stale⟩ s; stale vision > ⟨risk.vision_stale⟩ s.
  * Latency above its rolling p95.
* **Venue-rule risk, the largest.** Doubling the fee erases the OOS edge (Table 1).
* **Crowding.** The top 5 wallets carry ⟨conc.top5.is⟩ / ⟨conc.top5.oos⟩ of v2 P&L (IS / OOS); the wallet-clustered
  OOS CI is ⟨v2.oos.ci_wallet⟩.
* **Tail.** Kurtosis is ⟨v2.is.kurt⟩ / ⟨v2.oos.kurt⟩.
* **Factor exposure.** IS-only FF3 + momentum regression: α t = ⟨fac.alpha_t⟩, largest |t| ⟨fac.max_t⟩,
  R² ⟨fac.r2⟩.
* **Legal.** Courtsiding breaks ticket terms. Polymarket's international venue is close-only for US persons. We
  place no orders; real money: none.

### §7 Liquidity & capacity (60 words + Fig. 4)

* **Size.** v2 trades ⟨v2.is.notional_day⟩/day, ⟨v2.is.share_vol⟩ of match volume. The OOS per-share CI stays
  above 0 only at ≤ 1× (capital ⟨cap.1x.oos.cap⟩); 2× spans 0 and 5× loses (Fig. 4a).
* **Depth.** The stale depth the next reprice will hit has a median of ⟨liq.stale_pre⟩ / ⟨liq.stale_1s⟩ /
  ⟨liq.stale_2s⟩ at 0 / 1 / 2 s before the reprice. Moneyline spread median ⟨liq.spread⟩¢.
* **Costs bind.** The OOS break-even taker fee is ⟨fin.be_fee.before⟩ before fixed costs and ⟨fin.be_fee.central⟩
  after a central feed licence (ASSUMPTION ⟨fin.feed.central⟩/month). At the 1 s baseline, OOS trading P&L against
  that stack is ⟨cv.cal.oos.net_central⟩ (calibrated) and ⟨cv.pre.oos.net_central⟩ (pre-registered) per day
  (Fig. 4b).

### §8 Limitations & next steps (75 words)

* **The key uncertainty** is the stamp lag L (Eq. 3), which moves the break-even one for one. We would measure it
  in one live session with a licensed low-latency feed, timing bounce against stamp on every point.
* **Next steps.**
  * Licensing that feed turns the simulation into deployment. Polymarket US already buys official data and
    streams: Genius Sports for selected leagues, and ATP Tour streaming rights.
  * A faster feed moves left on the curve.
  * Venue partnerships: an organiser-consented camera.
* **What could break it:** fee rises, a longer order delay, faster rivals, a few wallets leaving, legal access.
  Table tennis is untestable and illiquid.

---

## 5. Equations (numbered; each is cited in the text)

```latex
% (1) taker fee, in §4
\begin{equation}\label{eq:fee}
  f(q) = r\,q(1-q)\ \text{per share}\quad\Longleftrightarrow\quad 10^{4}\,r\,(1-q)\ \text{bps of notional}
\end{equation}
% text: r = ⟨fee.rate⟩ today, so 250 bps at q = 0.5 (⟨fee.bps_q05⟩); v2 averages ⟨v2.is.fee_bps⟩ / ⟨v2.oos.fee_bps⟩ bps.

% (2) Markov point leverage, in §2
\begin{equation}\label{eq:lev}
  L_k = \Pr(\text{win}\mid \text{point } k \text{ won}) - \Pr(\text{win}\mid \text{point } k \text{ lost})
\end{equation}
% text: exact point-level chain (src/markov.py; Klaassen and Magnus 2001); mean |L| ⟨markov.lev⟩, ⟨markov.points⟩ points.

% (3) latency budget, in §4
\begin{equation}\label{eq:budget}
  \underbrace{t_b - \ell_{\mathrm{CV}} + V + \delta_{\mathrm{inf}}}_{\text{call}}
  + \delta_{\mathrm{net}} + \delta_{\mathrm{gw}} + D \;<\; t_b + L + R
  \;\Longleftrightarrow\;
  V < L + R - D - \delta_{\mathrm{inf}} - \delta_{\mathrm{net}} - \delta_{\mathrm{gw}} + \ell_{\mathrm{CV}}
\end{equation}
% symbols: t_b bounce; ℓ_CV call lead (0–50 ms); V feed delay; δ_inf 20 ms inference; δ_net network (Florida 67 ms /
% London 2 ms); δ_gw 2 ms gateway; D = venue taker delay 1 s; L = stamp lag t_stamp − t_b (UNMEASURED); R = reprice
% minus stamp (measured median ⟨lat.book_vs_stamp_signed⟩ s). Text: "the break-even V moves one for one with L: the
% CV call must be made about ⟨cv.call_before_stamp⟩ s before the stamp".
```

Eq. (3) is the whole reason the result depends on L. Write it so a judge can see it at a glance. If page width
forces it, split the inequality over two aligned lines; the equation number stays (3).

---

## 6. Main-text figures (`scripts/paper_figures.py`)

Common rules (style guide (b) applies):
* vector PDF drawn at final size; Source Sans 3 at 11 pt for every glyph;
* white background; no top or right spines; 0.6 pt axes;
* orange `#F26B21` for ours, black and greys for others, blue `#2C6FBB` only for third categories;
* IS solid, OOS dashed;
* bold panel letters (a)(b)(c)(d) top left;
* direct labels in place of legends where possible.

Every figure that shows CV-strategy numbers carries the label in its caption. **No figure title inside the axes.**

### Fig. 1 (p. 2): "The race is decided inside the venue's 1 s order delay." 6.5 × 2.05 in, two panels (widths 3.7 / 2.6 in)

* **(a) Information-tier ladder** (horizontal bars on one log-x axis, 1 ms – 60 s, "seconds after the point
  ends"). One row per source, fastest at the top. Fill: solid = measured by us, hatched = vendor-stated and
  unverified, orange = our components.

| Row | Value | Kind | Source key |
|---|---|---|---|
| Our CV engine, call-ready (L4 GPU, 120 fps, p50–p99) | ⟨cv.eng.p50⟩–⟨cv.eng.p99⟩ ms | measured, ours | `results/engine/online_vs_offline.json::headline.fp16_cl_fuse_compile_b1_realtime.stream.after_startup.call_ready_ms.{p50,p99}` |
| Our WebRTC → CV pipeline (own footage, not a match) | p50–p99 or the word "pending" | measured, ours | `results/webrtc/latency.json` if present, else newest `results/webrtc/summary_*.json::runs[*].capture_to_decision_ms.{p50,p99}`; else draw an empty row labelled "pending" |
| Network Florida → venue gateway | ⟨lat.net_fl⟩ s (live p50 ⟨lat.feed_p50⟩ ms) | measured | `results/decay/decay.json::latency_inputs.net_florida_s`; `results/engine/live_market_run.json::feed.latency.p50_ms` |
| In-venue tracking / camera at the court | ≤ 0.15 s | physical bound (see §14, issue 2) | `results/tier0/latency_sweep.json::sources[key=venue_camera].band_s` (≤ 0.05) widened to the 130–170 ms camera-to-screen test S4 (`results/home_stream/sub_second_routes.json::sources.S4`). Label it "not available to us" |
| Venue taker order delay | 1 s | venue rule | `latency_sweep.json::model.video` (parse "(1 s)") |
| Official umpire point stamp after the bounce | 1–3 s, **unmeasured** | model grid | `latency_sweep.json::grids.stamp_lag_s` |
| Licensed betting video (vendor-stated; none stated for tennis) | 0.5–8 s | vendor claim | `latency_sweep.json::sources[key=betting_video].band_s` |
| … sportsbook app streams (Genius BetVision, venue → phone) | 4–8 s | vendor claim | same `basis` string; cite NEXT.io |
| Fastest public stream of a Polymarket-listed match (Setka WebRTC, **preliminary**) | ⟨lat.webrtc_public⟩ s | measured | `results/home_stream/sub_second_routes.json::bottom_line.why_not_match` (regex `median ([0-9.]+) s`). **Never use the YouTube 20.2 s figure** |
| ESPN scoreboard / Polymarket sports feed / WTA API, behind the book | ⟨lat.espn⟩ / ⟨lat.pmsports⟩ / ⟨lat.wta⟩ s | measured | `research/v2/latency/results.json::summary.m1["espn:game"\|"pm_sports:game"\|"wta:point"].lead_vs_book_s.median` (negate) |

  Add a vertical marker in the margin: "book reprices ⟨lat.book_vs_stamp⟩ s **before** the official stamp
  (n = ⟨lat.n_points⟩)". Use `summary.m1.book_vs_official_T_s.median`. A log axis cannot show a negative time,
  so annotate it with an arrow pointing left from the stamp row.
* **(b) Held-out early calls** (x: call lead before contact, 0–200 ms; y: share, 0–1). Plot precision (orange) and
  recall (grey) for the snapshot rule (solid, primary) and the streamed engine (dashed), with Wilson 95 % bands
  on precision. Direct label: "⟨cv.tt.tp50⟩ of ⟨cv.tt.tp50⟩ out-calls correct at 50 ms (recall ⟨cv.tt.rec50⟩)".
  Source `results/tracking/summary.json::early_call.precision_recall_test_{snapshot,online}.<lead>ms`.
  Footnote in the caption: test set = held-out OpenTTGames videos, 120 fps, ⟨cv.tt.n_miss⟩ out balls and
  ⟨cv.tt.n_bounce⟩ in balls; the streamed engine matches the offline evaluation exactly
  (`online_vs_offline.json::...online_rule_precision_recall`).
* **Caption draft:** **Figure 1.** *The race is decided inside the venue's 1 s order delay: the book reprices
  before the official stamp, and only in-venue information arrives earlier.* (a) Latency of each information
  source (log scale); solid = measured by us, hatched = vendor-stated (unverified; none stated for tennis),
  orange = our pipeline. (b) Precision and recall of early out-calls against call lead on held-out 120 fps
  table-tennis video. Source: Polymarket CLOB websocket and WTA point-by-point log (2026-10-03); vendor pages
  (Table A9); `results/tracking/summary.json`; `results/engine/online_vs_offline.json`.

### Fig. 2 (p. 3): "Speed is the edge." 6.5 × 1.85 in, two panels (3.25 / 3.25 in)

* **(a) Who earns, by month** (Dec 2025 – Oct 2026; y: net 30 s markout after fee, ¢/share; zero line). Plot
  three lines with markers: fast tier (orange), every other taker in the same 0–3 s window (black), and the same
  prints copied 3 s later, held to resolution (grey). IS markers are filled and OOS markers hollow, with a light
  vertical band at the OOS start (Aug 25). Source: `results/alpha/alpha.json::A_source.{IS,OOS}.months[*].{fast_net30_c,others_net30_c,copy_3s_later_net_to_resolution_c}`.
  Note that the copy-3s row is held to resolution; say so in the caption. August appears in both periods: plot
  IS-Aug and OOS-Aug side by side, offset 0.15 month.
* **(b) v2 cumulative net P&L ($)** across IS → OOS. Lines:
  * base (orange; IS solid, OOS dashed);
  * **fees ×2** (dark grey);
  * **all costs ×2** (mid grey).

  Vertical line at the OOS start. Direct labels at the right end with the period totals.
  * Base daily series: `results/lowloss/daily.csv` (run `a`, books `u1_is`/`u1_oos`, policy `v2`). Its totals
    equal `results/v2/causal.json` (`total_pnl_usd` 40,425.72 / 3,687.54). Assert this.
  * Stressed series: recompute daily from `data/v2_trades_is_oos.parquet` with the **same row selection and
    lambdas** as `scripts/v2_cost_stress.py` (import them; do not reimplement): `fee_x2: pnl_ps − fee`,
    `costs_x2: pnl_ps − fee − 0.005`, × shares, summed by entry date.
  * **Assert the totals equal `results/v2/cost_stress.json::{is_eval,burned_oos}/{fee_x2,costs_x2}.total_pnl_usd`
    to the cent.** If the parquet is absent, draw the base curve only and add endpoint markers at the
    cost-stress totals. This is a figure re-draw of committed results, not a new evaluation; nothing is logged.
* **Caption draft:** **Figure 2.** *Speed is the edge: the fast tier earns every month, copying it 3 s later
  loses, and the frozen book survives out of sample only until fees double.* (a) Monthly net 30 s markout
  (¢/share, after each match's fee). (b) Cumulative net P&L of v2, measured at the fast tier's own fills (the
  opportunity at their speed, not our execution), with fees and all costs doubled. Source: Polymarket tapes;
  `results/alpha/alpha.json`, `results/lowloss/daily.csv`, `results/v2/cost_stress.json`.

### Fig. 3 (p. 4, centrepiece): "Signal decay: what a second of feed latency is worth." 6.5 × 3.3 in, 2 × 2

* **(a) Net $/day vs feed delay V** (log-x, 0.05–60 s; zero line).
  * Two readings: **calibrated stamp lag ⟨cv.cal.lag⟩ s ("calibrated, post hoc"), orange**, and **pre-registered
    2.0 s, black**. IS solid, burned OOS dashed. Seed bands at 15–20 % alpha: the 2.5–97.5 % of 20 seeds.
  * Data: `results/tier0/latency_sweep.csv`, rows `source=video, cv=own120, reading ∈ {tournament_lagcal,
    tournament}`, all grids (main + dense + extension + sensitivity_stamp_lag), deduplicated on x_s. Bands come
    from `results/tier0/latency_sweep_seeds.csv` (percentiles of `pnl_per_day_usd` per cell).
  * **Dotted vertical line at V = 1 s**, labelled "expected latency: licensed feed".
  * **Shaded source-class bands** behind the curves:
    * venue / in-venue ≤ 0.15 s (light grey);
    * licensed betting video 0.5–8 s (blue `#2C6FBB`, 12 % alpha);
    * sportsbook apps 4–8 s (cross-hatch inside the video band);
    * our measured public WebRTC stream at ⟨lat.webrtc_public⟩ s (thin vertical tick, "preliminary");
    * public score feeds ⟨lat.espn⟩–⟨lat.wta⟩ s (mid grey).

    Label the bands with short tags along the top of (a) only.
  * **Break-even markers:** open circles at `breakeven_video_delay.<reading>.<period>.breakeven_V_s_seed_mean_curve`,
    labelled with their values. Horizontal whisker = `..._seed_bootstrap_ci95`.
* **(b) Annualised Sharpe vs V.** Same encoding, axes and bands. Sharpe comes from `sharpe_ann` per cell; bands
  are percentiles of per-seed `sharpe_ann`. Direct labels at V = 1 s with the four Table 2 Sharpes.
* **(c) Market-side decay within a point** (x: seconds since the jump detection on the block clock; categorical
  bins 0 (same block), 1–2, 2–3, 3–5, 5–10, 10–30, then "baseline"; y: net 30 s markout, ¢/share after fee).
  * Plot the fast tier (orange) and every other taker (black), IS solid with filled markers and OOS dashed with
    hollow markers, with 95 % match-clustered CI whiskers.
  * Mark the 0.25–1 s bins "not resolvable (block-time tapes)" with a hatched gap.
  * Source: `results/decay/decay.json::tennis.subsets.{IS,burned_OOS}.curves.{fast,others}.net30.<bin>.{mean_c,ci_c}`.
  * Direct label: "pre-registered decay test: OOS ⟨decay.test.oos⟩ [CI] passes; pooled ⟨decay.test.pool⟩ fails".
* **(d) Replay on live-recorded books** (9 WTA matches, 2026-10-03; x: V ∈ {0, 0.5, 1} s; y: net ¢/share marked
  at the +30 s mid, with 95 % CI).
  * Three lines: stamp lag 1 / 2 / 3 s (light grey, black, orange). Zero line.
  * Overlay the sweep's per-share points at L = 2.0 (grey ×) from `replay.json::sweep_reference` for the level
    comparison.
  * Source: `results/replay/replay.json::cells["V{v}|lag{l}|lead_model|florida"].all.{per_share_mark_c,per_share_mark_ci95_c}`.
  * Direct label: "all ⟨rp.cells_neg⟩ of ⟨rp.cells⟩ cells < 0".
* **Caption draft (4 lines):** **Figure 3.** *Each second of feed latency costs the edge; at a 1 s licensed feed
  the answer depends on the unmeasured stamp lag, and a one-day replay on real books loses.* (a) Net $/day and
  (b) annualised Sharpe against feed delay V (log scale) for the calibrated (post hoc) and pre-registered stamp
  lags; IS solid, burned OOS dashed; bands span 20 seeds; dotted line = 1 s baseline; circles = break-even.
  (c) Net markout by seconds since a score move for the fast tier and all other takers. (d) Replay of nine
  matches recorded live on 2026-10-03 against their real books. **Simulated at an assumed feed latency (licensed
  feed not purchased); parameters measured.** Source: Polymarket tapes and recorded books;
  `results/tier0/latency_sweep.{json,csv}`, `results/decay/decay.json`, `results/replay/replay.json`.

### Fig. 4 (p. 5): "Capacity is small and costs bind." 6.5 × 1.85 in, two panels

* **(a) Size curve.** x: size multiplier {0.5×, 1×, 2×, 5×, all prints} (categorical). Left y: net $/day as bars,
  IS solid fill and OOS outline. Overlay: net ¢/share with 95 % CI as points with whiskers on a second panel row,
  *not* a twin axis. If space is too tight, plot ¢/share [CI] only and print the $/day in the caption. Capital
  goes under each tick ("$28k", …).
  Source: `results/financials/financials.json::strategies.v2.scaling.<size>.{IS,OOS}.{per_share_c,per_share_ci95_c,pnl_usd_per_day,capital_usd,sharpe_ann}`.
  Outer ceiling line: `strategies.v2.ceiling.{IS,OOS}.fast_tier_qualified_print_usd_per_day` (text label only;
  it is notional, not P&L).
* **(b) Per-day waterfall**, IS and OOS side by side: gross edge → taker fees → net trading → fixed costs
  (central; whisker low–high) → net after costs. Add a third, hatched mini-group, "CV @ 1 s, OOS", with the two
  Table 2 OOS $/day readings minus the same fixed stack. Label it "ASSUMPTION: feed licence central
  ⟨fin.feed.central⟩/month; video licence price unknown, not deducted".
  Source: `strategies.v2.periods.{IS,OOS}.waterfall.usd_per_day`, `strategies.v2.cost.daily.{low,central,high}`.
* **Caption draft:** **Figure 4.** *Capacity is small and costs bind: the out-of-sample edge survives only up to
  about 1× size, and a central feed licence costs more than the book earns out of sample.* (a) v2 net P&L and
  per-share edge by size (engine re-run with every cap scaled; no price-impact model beyond never exceeding the
  copied print, so larger sizes are optimistic). (b) Per-day economics at central fixed costs (whiskers:
  low–high). Fixed costs are cited estimates or labelled assumptions (Table A8). Source:
  `results/financials/financials.json`.

---

## 7. Main-text tables (booktabs; `siunitx` S columns; 11 pt; no `\resizebox`)

### Table 1 (p. 3): v2, IS | burned OOS (2 numeric columns, each 1.8 in wide)

**Caption (above):** **Table 1.** *The frozen fast-tier book (v2) earns in both periods at the fast tier's own
fills, but its out-of-sample edge does not survive doubled fees.*

| Row | IS (Feb 1 – Aug 25, ⟨v2.is.days⟩ d) | Burned OOS (Aug 25 – Oct 3, ⟨v2.oos.days⟩ d) | Source |
|---|---|---|---|
| Trades (matches) | 55,662 (7,639) | 10,412 (2,003) | `results/v2/causal.json::causal/{is_eval,burned_oos}/slip0.0.{n_trades,n_matches}` |
| Net ¢/share [95 % CI] | +1.38 [1.17, 1.59] | +0.60 [0.09, 1.13] | `…slip0.0.{per_share_c,per_share_ci_c}` |
| Net edge / fee, bps of notional | 273 / 120 | 114 / 179 | `results/v2/note_metrics.json::{is,burned_oos}.{net_edge_bps_of_notional,fee_bps_of_notional}` |
| Annualised return / volatility | 253 % / 17.5 % | 148 % / 22.2 % | `note_metrics::{ann_return_pct,ann_vol_pct}` |
| Sharpe (ann.) [bootstrap 95 % CI] | 14.5 [11.9, 17.4] | 6.7 [1.9, 12.3] | `note_metrics::sharpe_ann`; `results/rigor/rigor.json::bootstrap.{v2_is,v2_oos}.sharpe_ann_ci95` |
| Max drawdown / worst day (% capital) | −2.0 / −1.9 | −2.1 / −2.1 | `note_metrics::{max_dd_pct,worst_day_pct}` |
| Skew / worst month ($) | 0.53 / +2,543 | 0.33 / −434 | `note_metrics::{skew,worst_month_usd}` |
| Turnover (× capital per year) | 93 | 129 | `note_metrics::turnover_x_per_year` |
| Months positive | 7 / 7 | 2 / 3 | `causal.json::…{months_positive,months_total}` |
| **Costs stressed** (bold group label) | | | |
| +½ / +1 tick worse entry, ¢/share | +0.88 / +0.38 | +0.10 / −0.40 | `causal.json::…/slip0.005, slip0.01 .per_share_c` |
| Fees ×2, ¢/share [CI] (months +) | +0.77 [0.57, 0.98] (7/7) | −0.34 [−0.86, 0.19] (0/3) | `results/v2/cost_stress.json::{is_eval,burned_oos}/fee_x2` |
| All costs ×2, ¢/share [CI] | +0.27 [0.07, 0.48] | −0.84 [−1.36, −0.31] | `cost_stress.json::…/costs_x2` |

**Notes (11 pt, below):** "Held to resolution, net of each match's taker fee (Eq. 1) and traded spreads.
Measured at the fast tier's own fills: the opportunity at their speed, not our execution. Capital = 3 × peak
dollars locked (⟨v2.is.cap⟩ / ⟨v2.oos.cap⟩); returns arithmetic. CIs match-clustered; wallet-clustered OOS CI
⟨v2.oos.ci_wallet⟩. All costs ×2 = fee twice + half a 1¢ spread. OOS is burned (non-blind for v2)." **Source:**
Polymarket tapes; files above.

### Table 2 (p. 4): main result, the CV strategy at the 1 s baseline (4 numeric columns)

**Caption (above):** **Table 2.** *Main result: at a simulated 1 s licensed-feed baseline the strategy earns under
the calibrated stamp lag and roughly breaks even under the pre-registered one.* "Simulated at a 1 s licensed-feed
baseline: assumed feed latency (licensed feed not purchased); parameters measured."

Header: two `\cmidrule` groups, **Calibrated L = ⟨cv.cal.lag⟩ s (post hoc)** | **Pre-registered L = 2.0 s**. Each
group has IS (1 s-delay matches, ⟨cv.is.days⟩ d) | OOS (burned, ⟨cv.oos.days⟩ d).

| Row | Cal IS | Cal OOS | Pre IS | Pre OOS | Source (all at V = 1.0 s) |
|---|---|---|---|---|---|
| Net $/day [seed 95 % CI] | +94 [51, 125] | +57 [1, 130] | +15 [−9, 43] | +4 [−36, 62] | `results/tier0/latency_sweep.json::video_own120.{tournament_lagcal,tournament}["1"].{IS,burned_OOS}.{usd_per_day,usd_per_day_seed_ci95}` |
| Net ¢/share [95 % CI] | +1.11 [0.85, 1.38] | +0.66 [0.10, 1.19] | +0.40 [−0.32, 1.08] | **−0.38** [−2.08, 1.21] | `…{net_c_per_share,net_c_per_share_ci95}` |
| Sharpe (ann.) | 11.9 | 8.8 | 2.1 | 0.3 | `…sharpe_ann` |
| Ann. return / vol, % of capital | 118 / 9.9 | 92 / 10.3 | 30 / 14.1 | 12 / 33.4 | **derived** from `results/tier0/latency_sweep.csv` (same cell): `pnl_per_day_usd·365/capital_usd`; vol = that ÷ `sharpe_ann` (ratio of 20-seed means; say so) |
| Max DD % / worst day $ | −1.6 / −223 | −1.6 / −192 | −6.6 / −264 | −5.3 / −228 | `latency_sweep.csv::{max_dd_usd/capital_usd, worst_day_usd}` |
| Trades/day · wrong-call share | 65 · 12 % | 55 · 16 % | 26 · 35 % | 24 · 47 % | `n_trades/days`; `json::…wrong_call_share_of_trades` |
| Break-even V, s [95 % CI over seeds] | 2.23 [2.18, 3.39] | 2.14 [1.59, 2.19] | 1.09 [1.03, 2.04] | 1.01 [0.44, 1.05] | `latency_sweep.json::breakeven_video_delay.<r>.<p>.{breakeven_V_s_seed_mean_curve,breakeven_V_s_seed_bootstrap_ci95}` |

**Notes:**
* "Pre-registered OOS: positive $/day but negative ¢/share; both are shown."
* "Seed means over 20 simulated tournament draws; Sharpe is a ranking of a simulation and ignores model risk."
* "Turnover is not stored by the sweep and cannot be recomputed without a new OOS run; trades/day shown."
* "No equity curve at V = 1 s: the sweep stores no daily path. Fig. 3 shows the dispersion."
* "At stamp lag 1.0 s the same trader loses (IS ⟨cv.lag1.is.usd⟩, OOS ⟨cv.lag1.oos.usd⟩ per day; Table A1)."
* "V = 0 reproduces the published tier-0 headline exactly (`check_V0_equals_published_headline`)."

**Source:** Polymarket tapes; live-recorded books and WTA stamps (2026-10-03); files above.

### Table 3 (p. 5): what failed and what is pending (2 numeric-ish columns + verdict)

**Caption:** **Table 3.** *Every blind test of a tradable book failed or is pending; the latency mechanism
(fast tier minus other takers) held in every test.*

| Test (pre-registered unless marked) | IS | OOS / blind | Verdict | Source |
|---|---|---|---|---|
| H1 follow the jump · H2 favourites · H5 quote after jumps (post hoc), ¢/share | −1.61 · −0.41 · +0.22 | −2.08 · +0.80 · +0.16 | fail · no edge · inconclusive | `results/summary.json::{is,oos}.h1.J0.04_H30`, `.h2.lo0.85_hi0.97`, `.h5.J0.04_W30` `.mean_pnl_per_share_c` (CIs in Table A6 or the notes) |
| v1: copy the fast tier, ≤ $1k, hold (opened once, blind) | +1.16¢ | ⟨v1.oos.usd⟩ | failed OOS | `summary.json::is.h6_shadow.mean_pnl_per_share_c`, `oos.h6_shadow.total_pnl_usd` |
| v2 on ⟨u2.markets⟩ never-examined markets (U2), ¢/share [CI] | +2.02 [1.14, 2.93] | +1.22 [−0.19, 2.65] | **fail**; fast − others +3.09 / +2.16¢ | `results/expand/results.json::primary.{u2_is,u2_oos}`, `fast_minus_others_u2.{u2_is,u2_oos}.fast_minus_others_c` |
| Tier-0 v3 frozen rule, blind (U2), ¢/share | −0.22 | −0.52 | **fail** (all three sets) | `results/tier0_v3/blind.json::sets.{u2_is,u2_oos}.primary.per_share_c`, `verdicts` |
| Maker v1, side markets (blind OOS), ¢/fill [CI] | +2.02 (1 s/5 %) | +1.87 [−0.14, 3.86]; ⟨mk.oos.usd⟩ | **fail** | `results/maker/oos.json::consistency.is_1s5_net_c`, `primary.{value_c,ci95_c,verdict}`, `headline.total_pnl_usd` |
| Table tennis TT1–TT5 (⟨tt.matches⟩ evaluable matches) | no fast-tier wallet qualifies | — | untestable; median spread ⟨tt.spread⟩¢ | `results/tt/results.json::counts.evaluable_matches`, `TT2.any_wallet_qualified`, `TT4.book_snapshot.all.spread_c.median` |
| Replay at V = 1 s, L = 2 s, 9 live-recorded matches, ¢/share marked [CI] | — | −0.92 [−1.29, −0.57] | **loses** (⟨rp.cells_neg⟩/⟨rp.cells⟩ cells < 0) | `results/replay/replay.json::cells["V1|lag2|lead_model|florida"].all` |
| Forward test (blind, run once) · live paper session | — | ⟨fwd.cell⟩ · ⟨live.cell⟩ | pending until filled | `results/v2/forward.json` (`verdict_A_fast_tier`, `verdict_B_v2_book`, `primary_A_fast_minus_others_c`, `primary_m30_per_share_c`, `v2_trades`); `results/live/FINAL` + `summary.json::books.B1` |

**Notes:**
* "**Variants tried: ⟨var.total⟩** (⟨var.strategy⟩ strategy configurations incl. 44 for H1–H6, plus ⟨var.tier0⟩
  tier-0 scenarios, ⟨var.tier0v3⟩ tier-0 v3 rules, ⟨var.maker⟩ maker variants, 5 TT tests; latency-sweep and
  replay cells are sensitivities, none used to choose a rule; Table A4)."
* "Fees ×2: Table 1. v2 after central fixed costs: ⟨fin.v2.is.net_central⟩ IS, ⟨fin.v2.oos.net_central⟩ OOS per
  day (Fig. 4b)."

**Pending cells.** If `results/v2/forward.json` is missing at build time, print "pending (runs once ≈ 11:30 UTC
Oct 4)". If present, print "A ⟨…⟩¢ [lo, hi] PASS|FAIL · B ⟨…⟩¢ [lo, hi] PASS|FAIL · n = ⟨v2_trades⟩". If
`results/live/FINAL` is missing, print "running to Oct 4 11:30 UTC; ⟨B1 fills⟩ fills so far". **Never run
`scripts/forward_test.py`.**

---

## 8. Trim ladder (apply in order until `\pageref{lastmain} ≤ 5`) and grow ladder

**Trim, applied only if the measured build overflows:**
* **T1.** Shorten the box to ≤ 115 words: drop "max DD" from bullet 3 (it is in Table 1).
* **T2.** Abstract ≤ 135 words: drop "(⟨univ.volume⟩ traded)".
* **T3.** Cut §2 ¶3 to one sentence of citations and one of novelty (−20 words).
* **T4.** Merge Table 1's "Months positive" into the "Trades" row as "(7/7 months +)".
* **T5.** Table 3: move the H1/H2/H5 row to the notes as one sentence.
* **T6.** Fig. 2 to 1.7 in, Fig. 4 to 1.7 in.
* **T7.** Fig. 4(b) → appendix; F4 becomes one panel at half the height, and the economics go into the §7 text.
* **T8.** Move §6's factor bullet into the Table 1 notes.

**Never trim:**
* the 11 pt size anywhere;
* the CV label;
* the pre-registered column of Table 2;
* the replay;
* the costs-doubled rows;
* the peek count;
* the variant count;
* the failure rows.

**Grow (if ≥ N free lines remain on page 5 after the final build):**
* **G1 (≥ 14).** Promote the replay into its own **Fig. 5** with (a) the selected-match trace from
  `results/replay/selected_match_book.csv` + `points.csv` (orange = correct-call fill, grey × = missed) and (b) the
  current 3(d). Fig. 3 then becomes a 3-panel row (a, b, c) at 2.2 in.
* **G2 (≥ 6).** Add a Table 3 row "v2-safe U2 blind".
* **G3 (≥ 4).** Restore the T-trims in reverse order.

---

## 9. Appendix (after `\clearpage` References; floats numbered A1, A2, …; also 11 pt, to be safe)

Nothing a judge needs for scoring lives only here (track item 4). Each appendix float repeats its honesty label.

### 9.1 Appendix figures (`results/paper/figA*.pdf`)

| # | Content | Source |
|---|---|---|
| **A1** | v2 by regime (3 s/0 %, 3 s/3 %, 1 s/3 %, 1 s/5 %) and by month: ¢/share with CI bars, IS and OOS | `results/risk/risk_stats.json::regime`, `by_month` |
| **A2** | Forest plot of **every pre-registered or blind test** (H1, H2, H5, H6 OOS, v1, v2 U2 IS/OOS, v2-safe U2, tier-0 v3 ×3, maker blind, TT, replay): point and 95 % CI on one ¢/share axis, pass/fail colour-coded (orange = pass, black = fail) | the Table 3 sources + `results/lowloss/results.json` |
| **A3** | Rigor: v2 Sharpe vs the expected maximum Sharpe of N zero-skill trials (N = 44, 3,386, 3,410), IS and OOS, with bootstrap CIs; PBO bars for the three grids | `results/rigor/rigor.json::{psr_dsr,pbo_cscv,bootstrap}` |
| **A4** | Replay, selected match (Sun v Bucsa): mid, official points, fills by class at V = 1 s, cumulative marked P&L at V = 0 / 0.5 / 1 | `results/replay/{selected_match_book.csv,points.csv,replay.json::selected_story}` |
| **A5** | Latency-sweep extensions: official point feed (no CV), fast scout feed D = 0.25–1.5 s, CV-pessimistic sensitivity, the stamp-noise reading, and the lag-1/lag-3 curves | `latency_sweep.json::{official_feed_no_cv,fast_feed_extension,video_cv_pessimistic}`, `video_own120.{stamp,stamp_calibrated,tournament_lag1,tournament_lag3}` |
| **A6** | CV: spin-aware tennis landing error vs lead, baseline vs `bls`/`ukf` (**simulation**, 340 fps, 3.6 mm noise) | `results/spin/tennis/key_numbers.json::{baseline,bls,ukf}.sd_cm` |
| **A7** | Concentration: share of v2 P&L in the top-k wallets, matches and days, IS/OOS | `results/alpha/alpha.json::F_concentration` |
| **A8** | Full financial waterfall (v2, v2-safe, maker, tier-0) at low/central/high costs | `results/financials/financials.json` |

### 9.2 Appendix tables

| # | Content | Source |
|---|---|---|
| **A1** | **Latency sweep, every V × reading** (0 … 60 s; readings: calibrated 3.14, pre-reg 2.0, lag 1.0 stress, lag 3.0, stamp, stamp-calibrated): IS/OOS $/day and Sharpe. The lag-1.0 row block is the stress the team asked for. Split into two tables to stay at 11 pt | `latency_sweep.json::video_own120` |
| **A2** | Rigor pack: PSR, DSR at N = 44 / 3,386 / 3,410 under three variance sources, PBO (3 grids), MinTRL, bootstrap CIs | `rigor.json` |
| **A3** | Factor regressions: IS-only committed spec (headline), committed file (includes 5 OOS weekdays, flagged), IS calendar-day spec; α, t, betas with t, R² | `results/alpha/alpha.json::C_factor_neutral`; `results/v2/factor_regression.json` |
| **A4** | **Variant tally** by family with source and whether it chose anything | `results/paper/variants.json` (§12.12) |
| **A5** | Fixed-cost assumptions (low/central/high, label, basis, URL) | `financials.json::cost_assumptions` |
| **A6** | **Every OOS peek** (all lines of `results/oos_peeks.log` at build time): UTC time, class (blind first run / non-blind burned / descriptive / audit-reproduction / replay-live), one-line description (truncated at 110 chars) | `results/oos_peeks.log` → `results/paper/peeks.json`. Use a `longtable`; it is long, which is fine |
| **A7** | Pre-registration and deviation trail: file, commit, UTC time, what it froze | `git log --format='%h %aI %s' -- HYPOTHESIS*.md research/*/PREREG.md research/replay/PROTOCOL.md DEVIATIONS.md` (read by `build_paper.py`) |
| **A8** | Data sources and licences: API, granularity, period, terms note, access date | §9.3 list |
| **A9** | Latency ladder with citations and method (measured / vendor claim / model), with the S-numbers of `SUB_SECOND_ROUTES.md` | `latency_sweep.json::sources`, `sub_second_routes.json::sources`, `research/v2/latency/results.json` |
| **A10** | Table tennis TT1–TT5 verdicts, sample sizes and liquidity | `results/tt/results.json`, `results/decay/decay.json::table_tennis` |
| **A11** | Full risk register: kill switches (code), policy rules (pre-set), pre-trade checklist | `docs/RISK.md`, `results/engine/demo_run_L4.json::risk_config`, `results/paper/policy.json` |

### 9.3 References (natbib author-year; `refs.bib` keys)

* **Academic:**
  * `budish2015` (P1);
  * `aquilina2022` (P2);
  * `croxson2014` (P3);
  * `brown2014` (P4);
  * `brown2012` (Applied Economics 44(9), courtsiding; cite from its abstract, which is all we read);
  * `harvey2017` (P6);
  * `klaassen2001` (JASA);
  * `bailey2014` (deflated Sharpe, JPM);
  * `bailey2017` (PBO, J. Comp. Finance);
  * `harvey2016` (RFS, "…and the cross-section");
  * `politis1994` (stationary bootstrap, JASA);
  * `fama1993`;
  * `carhart1997`;
  * `voeikov2020` (TTNet/OpenTTGames);
  * `huang2019` (TrackNet);
  * `gossard2026` (BlurBall);
  * `tarashima2023` (WASB-SBDT).
* **Data and venue:**
  * Polymarket Gamma, Data and CLOB APIs, sports websocket, fee docs, geoblock and rate-limit docs;
  * Kalshi API;
  * ESPN scoreboard;
  * WTA API and point-by-point;
  * Ken French Data Library;
  * FRED DTB3.
* **Industry (vendor claims, used only as labelled claims):**
  * Stats Perform (realtime streaming; official WTA data);
  * NEXT.io on Genius BetVision;
  * Sportradar live streams;
  * Ably case study (Genius);
  * GL Systemhaus;
  * ISPreview;
  * The Desk (Super Bowl LX);
  * Regen Sports (Sportradar talk).
* **Polymarket's data and streaming partnerships:**
  * Gaming Intelligence, 5 Aug 2026, "Genius Sports agrees Polymarket prediction market deal"
    (https://www.gamingintelligence.com/finance/234424-genius-sports-agrees-polymarket-prediction-market-deal/),
    with the Nasdaq press release
    (https://www.nasdaq.com/press-release/polymarket-and-genius-sports-expand-role-official-data-exclusive-live-sports)
    as primary;
  * PR Newswire, 3 Aug 2026, Polymarket ATP Tour streaming rights
    (https://www.prnewswire.com/news-releases/polymarket-secures-exclusive-atp-tour-streaming-rights-for-prediction-markets-302841534.html).
* **Rules:**
  * ITIA TACP 2026;
  * ITF World Tennis Tour regulations 2026;
  * GQH Participant Terms v1.0.
* **Disclosure line** at the end of the References: "No real money was used. Simulated components are labelled.
  The authors hold no licensed data feed, no match footage and no court access. University of Florida students;
  `[team to confirm any other disclosures]`."

---

## 10. Rubric map (track criteria, 1–10 each; the band-10 text quoted from REQUIREMENTS items 48–52)

| Criterion (tie-break order) | Band-10 language | Where it is earned in the 5 pages | What would pull it below 10, and the guard |
|---|---|---|---|
| **5 Performance & Analytical Evidence** (tie-break 1) | "Exceptional analytical rigor, with thorough and convincing evidence of effectiveness." | Table 1 (all six metrics, both periods, skew, worst month, costs ×2, ½/1 tick); Fig. 2 (monthly + equity with stressed overlays); Table 2 + Fig. 3 (both readings, seed bands, break-evens); Table 3 (blind tests, replay, forward); §5 "Sharpe > 3" with the D9 bug, DSR, PBO, bootstrap; peek count; variant count | **Cap at 4** if the numbers do not match the code or OOS tuning is suspected. Guards: every number is a macro from JSON (§12); `reproduce.sh` regenerates the JSON; peeks all reported; burned OOS labelled non-blind; D9 disclosed. The risk to 10 is the calibrated reading being post hoc, so the pre-registered column sits beside it and the replay is shown |
| **1 Economic Foundation** (tie-break 2) | "Exceptional economic understanding, with highly compelling and well-evidenced reasoning for the strategy's success." | §2: Eq. (2) leverage, information tiers (Fig. 1a, all measured or cited), H6 in template form with commit, counterparty (slower takers), persistence (physics + licensing + venue hold), regime response (edge falls as protection falls, stays positive), literature (P1–P4, Brown 2012); Fig. 2a shows the prediction come true out of sample | A thin "why it persists" or no counterparty. Guard: ¶2 names the counterparty and the constraint class in the track's words and backs both with measured numbers |
| **2 Innovation** | "Highly innovative, groundbreaking approach that is original and distinct from conventional strategies." | Wallet-level latency-tier identification from public on-chain tapes; timing every public source against the official clock; CV that calls the point before contact (Fig. 1b, held-out, streamed at 120 fps on a GPU); the price of speed in $/day and Sharpe (Fig. 3) | Looking like "just courtsiding". Guard: §2 ¶3 states what is new against cited prior work; the paper's product is a *price of latency*, not a camera at the court (which it says is not feasible or allowed) |
| **3 Risk Management Plan** | "Highly detailed and effective approach, with multiple contingencies and a thorough understanding of strategy risks." | §6: hard limits, pre-set de-risking (with IS replay showing it never fires), code-level kill switches, venue-rule risk quantified (fees ×2), crowding/concentration (top-5 share, wallet-clustered CI), tail (kurtosis, worst day), factor regression, legal/settlement; Table A11 is the full register | Rules not tied to numbers, or not set in advance. Guard: every rule has a threshold and an evidence pointer; say which rules are code and which are policy |
| **4 Liquidity & Capital** | "Excellent, thorough analysis demonstrating deep market knowledge and practical application." | §7 + Fig. 4: capacity in $ by size (IS/OOS), outer ceiling, stale depth per point, spread, fee as the binding variable (break-even fee), fixed costs with sources, CV economics at 1 s against the feed licence; Fig. 1a latency ladder as the deployment constraint | An unsupported "$100k" claim. Guard: use the scaled OOS rows (≤ 1× survives) and stale depth; do not reuse NOTE.md's "$100k" (IS, onset labels, superseded) |

**Section → criterion map (track "FEEDS"):** Summary → EF + Perf; Hypothesis → EF + Innovation; Data → Perf;
Methodology → Innovation + Perf; Results → Perf; Risk → Risk; Liquidity → Liquidity; Limitations → Risk + Perf.

---

## 11. Track-rule map (REQUIREMENTS item → where in the new paper)

| Item | Requirement | Location |
|---|---|---|
| 2, 4 | ≤ 5 pages incl. floats; appendix optional | `\pageref{lastmain} ≤ 5` check; nothing scored only in the appendix |
| 3 | 11 pt everywhere, standard margins | §15 checks (font spans ≥ 10.9 pt on pp. 1–5, margins 72 pt) |
| 5, 19–21 | Hypothesis before results; committed first; template | §2 H6 box + commit trail (p. 1–2); first P&L float on p. 3 |
| 6, 7 | IS/OOS separate, net; ann. return, vol, Sharpe, max DD, turnover, equity curve for both | Table 1 + Fig. 2b (v2); Table 2 (CV at 1 s: all but turnover and equity, which are disclosed in its notes, §14 issue 1) |
| 8 | Risk and capacity sections | §6, §7, Fig. 4 |
| 9, 43 | Variant count; failures | Table 3 + notes; Table A4 |
| 10 | 8-section blueprint | §1–§8 in order |
| 13, 46 | One command reproduces | first-page footnote; macros from JSON |
| 16, 17, 37 | Cite every source; disclose pre-existing components; say what is new | footnote 2, References, §2 ¶3; third-party detector weights and datasets named in §4/References |
| 22 | Market scope | §3 first sentence (binary contracts on a public order book) |
| 24–27 | Holdout rule, once, report OOS and every peek | §3 split; §5 peek sentence; Table A6 |
| 28, 29 | Walk-forward inside IS; no lookahead | §4 Validation |
| 30, 31 | Costs in bps with justification; costs doubled | §4 Costs + Eq. (1); Table 1 "Costs stressed"; Fig. 2b |
| 32 | Survivorship, corporate actions, missing data | §3 |
| 33, 34 | p-hacking guards, plateau, DSR | §5 Sharpe > 3; Table A2 |
| 35 | Skew + worst month next to Sharpe; explain Sharpe > 3 | Table 1 rows; §5 paragraph (v2 and CV) |
| 36 | Regime / period breakdown | §2 ¶2 (regimes), Fig. 2a (months), Table 1 months positive, Fig. A1 |
| 40 | Factor regression | §6 bullet; Table A3 |
| 41 | Capacity in $, ADV fraction, costs-doubled sensitivity | §7, Fig. 4 |
| 42 | Limits, de-risking, tail/regime | §6 |
| 44, 45 | No real money; licences/ToS | footnote p. 1; §6 Legal; References disclosure |
| Honesty | CV label, live session, forward test | Table 2 caption, Fig. 3 caption, abstract, box; Table 3 pending cells |

---

## 12. Number registry: every number the paper shows, with its source

The format column is how `build_paper.py` prints the value. "Value" is as checked on 2026-10-03, for
orientation only. **J** = JSON key, **C** = CSV, **D** = derived in `build_paper.py` from the listed keys (show the
formula in a code comment), **P** = `results/paper/policy.json` (constants copied with file:line provenance).

### 12.1 Universe and data

| Key | Value | Source |
|---|---|---|
| univ.matches | 13,084 | J `results/summary.json::universe.matches` |
| univ.volume | $2.84B | J `summary.json::universe.volume_usd` |
| univ.is / univ.oos | 10,467 / 2,617 | J `summary.json::universe.{is,oos}` |
| univ.oosstart | 2026-08-25 14:15 UTC | J `summary.json::universe.oos_start` |
| univ.first / univ.last | 2025-10-08 / 2026-10-03 | J `results/v2/note_metrics.json::holdout.{first_start,last_start}` |
| univ.oos_time / univ.oos_vol | 10.7 % / 21.2 % | J `note_metrics::holdout.{oos_share_of_time,oos_share_of_volume}` |
| univ.timesplit | 2026-07-23 | J `note_metrics::holdout.time_based_20pct_start` |
| univ.minvol | $5,000 | P `src/tape.py:12 MIN_VOL` (import it) |
| data.offsetcap / data.nofee | 6 / 2,889 | J `note_metrics::data_gaps.{tapes_at_offset_cap_10500_rows,no_fee_schedule_matches}` |
| data.res5050 | 2.89 % | J `results/risk/risk_stats.json::settlement.all.res_50_50_pct` |
| data.blocklag / .n | 1.98 s / 5,472 | J `results/decay/decay.json::latency_inputs.block_lag_s.{median,n}` |
| markov.points / markov.lev | 161 / 5.7 % | J `results/leverage_stats.json::atp.{points_per_match,mean_abs_leverage}` |
| fee.rate / fee.bps_q05 / fee.bps_q09 | 5 % / 250 / 50 bps | J `results/financials/financials.json::strategies.v2.periods.OOS.breakeven_taker_fee.uniform_rate_charged`; `note_metrics::fee_formula_bps_today` |
| u2.markets | 11,307 | J `results/expand/results.json::universe.u2_markets` |
| prereg.hyp.commit / .time | 7232986 / 2026-10-03 05:50 EDT | D `git log --diff-filter=A --format='%h %aI' -- HYPOTHESIS.md` |

### 12.2 Fast tier (Fig. 2a, §1, §2)

| Key | Value | Source |
|---|---|---|
| ft.months.is / .oos | 9/9 · 3/3 | J `results/alpha/alpha.json::headline.fast_tier_net30_c_months_positive` (**not** NOTE.md's 8/8: the JSON counts Dec 2025) |
| ft.c.is / .oos | +0.93 / +0.75 ¢ | J `alpha.json::headline.fast_tier_net30_c_print_weighted` |
| oth.c.is / .oos | −0.89 / −1.43 ¢ | J `alpha.json::headline.others_net30_c_month_mean` |
| copy3.c.is / .oos | −1.05 / −1.59 ¢ | J `alpha.json::headline.copy_3s_later_c` |
| ft.wallets.first / .last | 4 / 131 | J `summary.json::is.h6_walkforward[0].n_wallets`, `oos.h6_walkforward[-1].n_wallets` |
| ft.slope / .t | −0.20 ¢/month / −3.98 | J `alpha.json::headline.fast_tier_slope_c_per_month.{IS,IS_t}` |
| Fig. 2a series | per month | J `alpha.json::A_source.{IS,OOS}.months[*]` |
| h4 book leads public score | 44.5 s (n 75) | J `summary.json::h4.{median_lead_s,n}` (Table A9 only) |

### 12.3 v2 (Table 1, Fig. 2b, §5–§7)

The Table 1 cells use keys `v2.{is,oos}.{trades,matches,days,c,ci,net_bps,fee_bps,ret,vol,sr,sr_ci,dd,worstday,
skew,worstmonth,turnover,mpos,slip05,slip10,fx2.c,fx2.ci,fx2.mpos,cx2.c,cx2.ci}`, with the sources given row by
row in §7. The Table 2 cells use keys `cv.{cal,pre}.{is,oos}.{usd,usd_ci,c,c_ci,sr,ret,vol,dd,worstday,tpd,wrong,
be,be_ci}`. Additional keys:

| Key | Value | Source |
|---|---|---|
| v2.is.cap / v2.oos.cap | $28,302 / $22,754 | J `note_metrics::{is,burned_oos}.capital_usd` |
| v2.is.pnl / v2.oos.pnl | $40,426 / $3,688 | J `results/v2/causal.json::causal/{is_eval,burned_oos}/slip0.0.total_pnl_usd` |
| v2.is.hs_bps | 98.9 bps | J `note_metrics::is.half_spread_0.5c_bps_of_notional` |
| v2.is.kurt / v2.oos.kurt | 4.30 / 3.26 | J `note_metrics::{is,burned_oos}.kurtosis_pearson` |
| v2.is.worstday_usd / .oos | −$551 / −$469 | J `causal.json::…slip0.0.worst_day_usd` |
| v2.is.notional_day | $7,182 | J `note_metrics::is.usd_traded_per_day` |
| v2.is.share_vol | 0.07 % | J `note_metrics::is.v2_usd_traded_share_of_match_volume` |
| v2.trades_per_day | 270 | D `n_trades / days` (IS) |
| v2.oos.ci_wallet | [−0.45, 2.38] | J `results/financials/pm_compute.json::p07_wallet_clustered_ci.burned_oos.ci95_c_wallet_clustered` (**NOTE.md's [−0.60, 2.11] is stale; do not reuse it**) |
| v2.oos.fx2.c / .mpos | −0.34 ¢ / 0/3 | J `results/v2/cost_stress.json::burned_oos/fee_x2.{per_share_c,months_positive}` |
| v2.onset.is.sr / v2.onset.oos.c | 16.8 / +0.76 ¢ | J `causal.json::onset/{is_eval,burned_oos}/slip0.0.{sharpe_ann,per_share_c}` (D9 before/after) |
| v2.reg.3s0/3s3/1s3/1s5 | 1.96 / 1.36 / 1.45 / 1.02 ¢ (IS) | J `risk_stats.json::regime.is_eval.{"3s/0%","3s/3%","1s/3%","1s/5%"}.per_share_c` (CIs in Fig. A1) |
| decay.sameblock.share | 98 % ($44,452 of $45,147) | D `results/decay/audit_sameblock.json::v2_backtest_trades["IS+burned_OOS"].{same_block.pnl_usd / all_matched.pnl_usd}` |
| conc.top5.is / .oos | 81 % / 142 % | J `alpha.json::headline.top5_wallet_share_of_pnl` |
| risk.corr_sameday | 0.0013 | J `risk_stats.json::correlation.is_eval.implied_mean_pairwise_corr_same_day` |

### 12.4 Rigor and factor (§5, §6, Tables A2–A3)

| Key | Value | Source |
|---|---|---|
| rig.N / rig.N44 | 3,410 (3,386 without the v2-safe grid) / 44 | J `results/rigor/rigor.json::psr_dsr.N.{all_plus_v2safe_grid,all_NOTE_s8,H1_H6}` |
| rig.dsr.is | 0.997 | J `rigor.json::psr_dsr.rows[series=v2_is].dsr["N3386/sizing_grid_55"].dsr` |
| rig.dsr.oos (range) | 0.075–0.839 | J `alpha.json::headline.v2_oos_dsr_N3386_range` |
| rig.sr0.oos | 11.0 | J `rigor.json::psr_dsr.rows[v2_oos].dsr["N3386/null"].sr0_ann` |
| rig.pbo.sizing / .lowloss | 0 % / 15 % (selection rule 42 %) | J `rigor.json::pbo_cscv.{sizing_55_res_actual_sharpe,lowloss_24_sharpe,lowloss_24_selection_rule}.pbo` |
| rig.boot.oos / p≤0 | [1.9, 12.3] / 0.0023 | J `rigor.json::bootstrap.v2_oos.{sharpe_ann_ci95,p_sharpe_le_0}` |
| fac.alpha / fac.alpha_t / fac.max_t / fac.r2 / fac.n | 0.80 %/day / 8.48 / 1.36 / 3.3 % / 138 d | J `alpha.json::C_factor_neutral.IS_committed_spec.{alpha_pct_per_day,alpha_t,max_abs_factor_t,r2,n_days}` (**the IS-only spec; the committed file includes 5 OOS weekdays**) |

### 12.5 CV, vision and engine (Fig. 1b, §4)

| Key | Value | Source |
|---|---|---|
| cv.tt.n_miss / n_bounce | 41 / 130 | J `results/tracking/summary.json::n_flights.test.{MISS,BOUNCE}` |
| cv.tt.tp50 / fp50 / rec50 / wil50 | 11 / 0 / 27 % / [0.74, 1] | J `summary.json::early_call.precision_recall_test_snapshot["50ms"].{tp,fp,recall,precision_wilson95}` |
| cv.tt.tp0 / rec0 | 24 / 59 % | J `…["0ms"]` |
| cv.tt.det_recall / within5 | 96.7 % / 93.9 % | J `summary.json::detection_accuracy_pooled[split=test,source=tracked].{recall,within5}` |
| cv.eng.fps / dropped / frames | 119.9 / 0 / 102,120 | J `results/engine/online_vs_offline.json::headline.fp16_cl_fuse_compile_b1_realtime.stream.{fps,dropped,frames}` |
| cv.eng.p50 / p99 | 4.6 / 12.2 ms | J `…stream.after_startup.call_ready_ms.{p50,p99}` |
| cv.eng.emit50 | 6.9 ms | J `…stream.after_startup.emitted_call_latency_ms.p50` |
| cv.laptop.fps | 50.6 (not real-time) | J `results/engine/vision_bench.json::summary[0].fps_sustained` (appendix) |
| cv.spin.bls200 / base200 | 0.57 / 5.76 cm (**simulation**) | J `results/spin/tennis/key_numbers.json::{bls,baseline}.sd_cm["200"]` (appendix) |
| cv.webrtc.p50 / p99 | pending | J `results/webrtc/latency.json` or `summary_*.json::runs[*].capture_to_decision_ms.{p50,p99}`, `video_leg_ms.*`; else "pending" |
| cv.inf | 20 ms | J `decay.json::latency_inputs.cv_assumed_s` |

### 12.6 Latency ladder (Fig. 1a, §2, Eq. 3)

| Key | Value | Source |
|---|---|---|
| lat.book_vs_stamp / signed | 1.2 s / −1.16 s | J `research/v2/latency/results.json::summary.m1.book_vs_official_T_s.median` |
| lat.n_points | 482 | J `…book_vs_official_T_s.n` |
| lat.espn / lat.pmsports / lat.wta | 28.2 / 30.0 / 44.1 s behind the book | J `…summary.m1["espn:game"\|"pm_sports:game"\|"wta:point"].lead_vs_book_s.median` (negate) |
| lat.lead_gt13 | 0 of 295 | D from `…m1.*.lead_vs_book_s.{share_gt_1p3,n}` |
| lat.prints_with_move | 98 % | J `…summary.trades_around_reprice["(-0.5, 0.0]"].share_usd_with_move` |
| lat.webrtc_public | 12.2 s (preliminary) | D regex on `results/home_stream/sub_second_routes.json::bottom_line.why_not_match`. **Exclude the YouTube figure** |
| lat.net_fl / lat.net_ldn | 67 / 2 ms | J `decay.json::latency_inputs.{net_florida_s,net_london_s}` |
| lat.feed_p50 | 65 ms | J `results/engine/live_market_run.json::feed.latency.p50_ms` |
| venue.delay | 1 s | D regex "order delay \(([0-9.]+) s\)" on `latency_sweep.json::model.video` |
| bands | see Fig. 1a | J `latency_sweep.json::sources[*].band_s` |

### 12.7 CV strategy at the 1 s baseline (Table 2, Fig. 3a–b, abstract, box)

The cell sources are in §7. Additional keys:

| Key | Value | Source |
|---|---|---|
| cv.cal.lag | 3.14 s | D regex on `latency_sweep.json::grids.video_stamp_lag_sensitivity.tournament_lagcal` |
| cv.pre.lag | 2.0 s | J `latency_sweep.json::model.revised_primary.stamp_lag` |
| cv.{cal,pre}.{is,oos}.{usd,sr,c} | +94 / +57 / +15 / +4; 11.9 / 8.8 / 2.1 / 0.3; … | J `video_own120.{tournament_lagcal,tournament}["1"].{IS,burned_OOS}` |
| cv.{cal,pre}.be.{is,oos} | 2.23 / 2.14 / 1.09 / 1.01 s | J `breakeven_video_delay.{tournament_lagcal,tournament}.{IS,burned_OOS}.breakeven_V_s_seed_mean_curve` |
| cv.lag1.{is,oos}.usd | −$6 / −$11 | J `video_own120.tournament_lag1["1"].{IS,burned_OOS}.usd_per_day` |
| cv.call_before_stamp | 0.89 s | D `cv.pre.lag − cv.pre.be.is − cv.inf` |
| cv.is.days / cv.oos.days | 103 / 40 | C `latency_sweep.csv::days` (IS = 1 s-delay matches from 2026-05-15 only; say so) |
| cv.{cal,pre}.oos.net_central | −$110 / −$163 per day | D `usd_per_day − financials.json::strategies.v2.cost.daily.central` (label ASSUMPTION; video licence not included) |
| cv.v0.check | IS $88.79 · OOS $46.43, identical | J `latency_sweep.json::check_V0_equals_published_headline` |
| cv.seeds / runs | 20 / 18,880 | J `latency_sweep.json::{grids.seeds,run.n_runs}` |

### 12.8 Market-side decay (Fig. 3c)

| Key | Value | Source |
|---|---|---|
| decay curves | IS fast +1.18 (0 s) … ; others −0.88 … | J `decay.json::tennis.subsets.{IS,burned_OOS}.curves.{fast,others}.net30.*` |
| decay.test.oos / .pool | +0.66 [0.45, 0.87] passes / +0.19 [−0.26, 0.46] fails | J `decay.json::tennis.subsets.{burned_OOS,"IS+burned_OOS"}.decay_test.{stat_c,ci_c,decays}` |
| decay.prints / detections | 9.56 M / 268,345 | J `decay.json::tennis.meta.{prints,detections}` |

### 12.9 Replay (Fig. 3d, Table 3)

| Key | Value | Source |
|---|---|---|
| rp.v1l2.c / ci / usd_mark / usd_hold | −0.92 [−1.29, −0.57] / −$229 / −$387 | J `replay.json::cells["V1|lag2|lead_model|florida"].all.{per_share_mark_c,per_share_mark_ci95_c,pnl_mark_usd,pnl_hold_usd}` |
| rp.beat / of | 35 / 467 | J `…all.{calls_beat_book,calls_with_reprice}` |
| rp.cells_neg / rp.cells | 36 / 36 | D count of `cells[*].all.per_share_mark_c < 0` |
| rp.best | lag 3, V 0: −0.07 [−0.38, 0.27] | D argmax over cells |
| rp.matches / points | 9 / 500 replayable of 994 | J `replay.json::matches` (len), `…all.{replayable_points,official_points}` |

### 12.10 Blind tests and failures (Table 3)

The sources are in the Table 3 spec (§7). Extra keys: `v1.oos.usd` = −$36,056; `mk.oos.usd` = −$379; `tt.matches` =
27; `tt.spread` = 94¢. H1 "all 20 variants < 0" is D: the count of `summary.json::is.h1.*.mean_pnl_per_share_c < 0`.

### 12.11 Risk, capacity, financials (§6, §7, Fig. 4)

| Key | Value | Source |
|---|---|---|
| risk.order_usd / netcap / zone / daily_stop / feed_stale / vision_stale | $1,000 / 100 / 0.05–0.95 / $1,000 / 2 s / 1 s | J `results/engine/demo_run_L4.json::risk_config.{max_order_usd,net_cap_shares,zone,daily_stop_usd,feed_stale_ms,vision_stale_ms}` (cross-check against `engine/risk/limits.py RiskConfig()` defaults by import; fail if they differ) |
| risk.daily_stop_sigma | 3.86 | D `daily_stop / rigor.json::sharpe_moments.v2_is.sd_daily_usd` |
| risk.cap_realised / lock_over_4h | $34,818 / 24.9 % | J `risk_stats.json::liquidity_capital.is_eval.{capital_usd_3x_peak_realised,realised_lock_over_4h_pct}` |
| risk.trail_min | +0.74 ¢ | J `pm_compute.json::p25_kill_rules_is.trailing_30d_edge_rule_v2_is.trailing_edge_c_min` |
| pol.trail_half / pol.dd_stop | 0.3 ¢ / 5 % | P `docs/RISK.md` "Daily kill-switch rules" table (copy with line numbers) |
| cap.{0.5x,1x,2x,5x,all}.{is,oos}.* | see Fig. 4a | J `financials.json::strategies.v2.scaling` |
| cap.ceiling.is / .oos | $82,325 / $105,490 per day | J `strategies.v2.ceiling.{IS,OOS}.fast_tier_qualified_print_usd_per_day` |
| fin.waterfall | IS 282 → −86 → 196; OOS 237 → −144 → 92 $/day | J `strategies.v2.periods.{IS,OOS}.waterfall.usd_per_day` |
| fin.fixed.{low,central,high} | $42 / $167 / $332 per day | J `strategies.v2.cost.daily` |
| fin.v2.{is,oos}.net_central | +$29 / −$75 | J `financials.json::headline[strategy=v2…,period=IS\|OOS…].net_after_costs_usd_per_day.central` |
| fin.be_fee.before / .central | 8.2 % / 2.4 % | J `strategies.v2.periods.OOS.breakeven_taker_fee.{rate_before_fixed_costs,rate_after_central_fixed_costs}` |
| fin.feed.central | $5,000/month | J `financials.json::cost_assumptions.feed_licence.central` (label "ASSUMPTION") |
| liq.stale_pre / 1s / 2s | $222 / $379 / $565 | J `research/v2/latency/results.json::summary.stale_depth.{pre,pre1s,pre2s}.median_usd` |
| liq.spread | 1 ¢ | J `…summary.side_market_spreads_live.moneyline.median_spread` |
| liq.trade_med | $11 | J `risk_stats.json::liquidity_capital.is_eval.usd_per_trade_quantiles["0.5"]` |

### 12.12 Variants (`results/paper/variants.json`, Table 3 notes, Table A4)

| Family | Count | Source / rule |
|---|---|---|
| H1–H6 | 44 | J `rigor.json::psr_dsr.N.H1_H6` |
| v2 lenses (exit, sizing, selection, cross-market, latency, Kalshi) | 3,342 | D `N.all_NOTE_s8 − N.H1_H6` |
| v2-safe grid | 24 | D `N.all_plus_v2safe_grid − N.all_NOTE_s8` |
| Tier-0 pre-registered scenarios | 432 | C rows of `results/tier0/grid.csv` with `period == "IS"` (432; the OOS rows repeat the same scenarios) |
| Tier-0 v3 IS grid | 360 | C rows of `results/tier0_v3/is/grid.csv` with `kind == "grid"` (360; the 2 `ref` rows are references) |
| Maker v1 evaluated variants | 8 | J `len(results/maker/oos.json::variants_evaluated)` |
| Cost-stress cases | 4 | J keys of `cost_stress.json` minus `base` per period |
| TT tests | 5 | the TT1–TT5 keys in `results/tt/results.json` + `decay.json` |
| Sensitivities, none chosen: latency-sweep cells, replay cells | n | C rows of `latency_sweep.csv`; `len(replay.json::cells)` |

**var.total** = the sum of the first eight rows. State plainly that the sensitivities chose nothing.

### 12.13 Peeks (`results/paper/peeks.json`)

* `peeks.n` = the number of lines in `results/oos_peeks.log` **at build time** (65 on Oct 3; do not use
  `note_metrics.json::oos_peeks_log.lines`, which says 19 and is stale).
* Classes come from case-insensitive keyword rules, applied in this order:
  * `REPLAY|live paper|session` → live;
  * `audit|reproduc|RE-RUN|rebuild|recompute` → audit;
  * `descriptive|no strategy|no P&L|plumbing|selection check|provenance` → descriptive;
  * `non-blind` → non-blind;
  * `first run|first use|blind|PREREG` → blind first run;
  * anything else → other.

  Print the per-class counts. Table A6 lists every line with its class.
* `peeks.rule_changes` = 2 (v2 itself; the D9 fix). Policy fact, P with source `DEVIATIONS.md`.

### 12.14 Pending slots

| Key | When present | When absent |
|---|---|---|
| fwd.status, fwd.cell | `results/v2/forward.json`: `verdict_A_fast_tier`, `verdict_B_v2_book`, `primary_A_fast_minus_others_c` [v, lo, hi], `primary_m30_per_share_c` [v, lo, hi], `v2_trades`, `v2_matches` | "pending" |
| live.status, live.cell | `results/live/FINAL` exists → `results/live/summary.json::books.B1.{fills,net_c_per_share,pnl}` | "running to 2026-10-04 11:30 UTC" + `books.B1.fills` so far |
| cv.webrtc.* | §12.5 | "pending" |

### 12.15 Policy constants (`results/paper/policy.json`, each with file:line)

* Detector: ≥ 4¢ move, 10 s VWAP against the prior 60 s.
* Wallet qualification: ≥ 30 prints within 0–3 s, ≥ 10 matches, t > 3.
* Shrinkage n₀ = 200.
* Zone 0.05–0.95; LOCK_S = 4 h.

Sources: `src/fasttier.py`, `src/v2.py`, `src/tiers.py`, `HYPOTHESIS_V2.md`. Import a constant where it exists;
otherwise copy it and record the line. Also copy the trailing-edge and drawdown policy from `docs/RISK.md`.

---

## 13. Honesty guardrails (cap-at-4 and disqualification risks)

* **Literal labels, attached:**
  * Table 2 caption, Fig. 3 caption, the abstract sentence, box bullets 1 and 3, the first-page footnote: "assumed
    feed latency (licensed feed not purchased); parameters measured" (Table 2 and Fig. 3 also say "simulated at
    a 1 s licensed-feed baseline").
  * Table 1, Fig. 2b and §4 v2: "measured at the fast tier's own fills: the opportunity at their speed, not our
    execution".
  * Fig. A6 and any spin-tennis number: "simulation".
  * Fig. 3d and Table 3: "replay on real books; assumed 1 s feed; illustration, one day".
* **Never write** that we received or watched match video, have a courtside camera, bought a licensed feed, or
  used live ATP/WTA data. The build greps the PDF text (case-insensitive) and fails on any of:
  * "our feed"; "our licensed"; "licensed feed we"; "we licensed"; "we purchased"; "we bought";
  * "received video"; "match footage we"; "our camera at"; "courtside camera we"; "live ATP data"; "live WTA data".

  Allowed: "no courtside camera", "not purchased", "we hold no licensed feed".
* **Genius Sports scope.** The Aug 2026 deal is for **Polymarket US**, for *selected* leagues (Serie A, MLB, NHL,
  UFC, Liga MX and others); **tennis is not named**. Write: "Polymarket US already licenses official data and live
  streams (Genius Sports for selected leagues; ATP Tour streaming rights)". Do **not** write that Polymarket buys
  tennis data from Genius.
* **The calibrated lag is post hoc.** Always print it next to the pre-registered reading, never alone. The
  break-even "≈ 1.0–1.1 s" belongs to the pre-registered reading only; the calibrated one breaks even at
  ≈ 2.1–2.2 s.
* **Pre-registered OOS sign split.** $/day is positive and ¢/share negative; print both.
* **The replay loses at every V and lag**; it must not be framed as support for the level.
* **Real money: none** (TERMS 5.3); all P&L is paper or simulated.
* **Burned OOS** is always labelled "burned (non-blind for v2)".

---

## 14. Open issues for the orchestrator or team (decide before or during the build)

1. **No CV equity curve, and no turnover, at V = 1 s.** The track wants an equity curve and turnover for both
   periods "of the strategy". The sweep stored only per-cell aggregates. The IS daily path would need a new IS
   run (allowed). **The OOS path would need a new burned-OOS evaluation, which this task forbids.** The plan
   discloses the gap in the Table 2 notes. v2 (Table 1 + Fig. 2b) carries the full metric set and equity curve as
   the measured book. Decide whether that is acceptable or whether a team member wants to authorise a logged
   re-run. The default is to disclose and not re-run.
2. **"venue/official ≤ 0.15 s" band.** The research does not support "official ≤ 0.15 s". The official umpire
   stamp is an *unmeasured* 1–3 s after the bounce (`grids.stamp_lag_s`), and the book reprices 1.2 s *before* it.
   Only in-venue tracking or a camera at the court is ≤ 0.15 s, and that is not available to us. Fig. 1a and
   Fig. 3 therefore show "in-venue ≤ 0.15 s" and "official stamp 1–3 s (unmeasured)" as separate rows.
3. **Stale numbers in `docs/NOTE.md` must not be carried over:**
   * fast-tier months 8/8 (JSON: 9/9);
   * wallet-clustered CI [−0.60, 2.11] (JSON: [−0.45, 2.38]);
   * "19 peeks" (log: 65+);
   * "$100k capacity" (superseded by the scaled OOS rows);
   * "$8.1k at the touch, $61k within 2¢" (no committed JSON source: `scripts/live_books.py` prints to stdout).

   Drop the depth figure, or have a script write it to JSON. That would read forward-window books descriptively,
   which needs an `oos_peeks.log` line, so dropping it is the default.
4. **The 12.2 s public-stream figure** lives in a string in `sub_second_routes.json`. The underlying probe files
   in `research/home_stream/latency/` are untracked, and their medians differ by run (12.06 s granite, 13.49 s
   turquoise). Keep "preliminary" and the regex source, or commit the probe outputs and cite their median.
5. **Factor regression.** Use the IS-only spec from `alpha.json` (138 days). The committed
   `results/v2/factor_regression.json` includes 5 burned-OOS weekdays; show it only in Table A3, flagged.
6. **Author names** are placeholders: `[Author names — team to fill]`, emails `[…]`.
7. **Live session** is in warm-up as of Oct 3 21:05 UTC. Its cell stays "running/pending" unless `FINAL` exists.
8. **`docs/COMPLIANCE.md`** still points at the old NOTE sections (§1–§7, Tables 1–2). After the build, update its
   "Note sections" line and items 2–10, 13, 35, 36, 40–42 to the new §1–§8, Tables 1–3, Figs 1–4 and appendix
   references (this task owns that edit).

---

## 15. Build acceptance checks (`build_paper.py` must fail on any of these)

1. **Five pages.** `\pageref{lastmain}` ≤ 5 (read from `main.aux`). References start on a new page.
2. **11 pt.** pymupdf, pages 1–5: no text span < 10.9 pt, except superscript-flagged spans (footnote markers,
   exponents, math scripts). This includes text inside the embedded figure PDFs.
3. **Margins.** No text bbox within 72 pt of the left or right edge, or of the top or bottom edge except the
   header and footer.
4. **Macros.** No `COURTSIDE: missing number` in the log; every ⟨key⟩ in §12 resolves.
5. **Consistency asserts.**
   * Fig. 2b totals = `cost_stress.json`;
   * daily.csv totals = `causal.json`;
   * the Table 2 cells equal `latency_sweep.json`;
   * the RiskConfig defaults equal `demo_run_L4.json::risk_config`;
   * V = 0 check true.
6. **Honesty grep** (§13), and the presence of the literal CV label at least 3 times on pages 1–5.
7. **Pending logic.** The forward and live cells are filled only from existing files; `forward_test.py` is never
   imported or run.
8. **LaTeX log.** No overfull hbox > 1 pt; no undefined references or citations.
9. **Look at it.** Render every page at 110 dpi to `results/paper/pages/`. Inspect against
   `docs/paper/reference/*.png` (house look) and the style-guide rule-10 list:
   * no widows or orphans;
   * no heading stranded at a page foot;
   * each float on the same page as its first reference or the next one;
   * title block ≤ 1.55 in;
   * links dark slate, not boxed.
10. **Fonts.** Every font is embedded and comes from `docs/paper/fonts/` (`pdffonts`, or pymupdf `get_fonts`).
