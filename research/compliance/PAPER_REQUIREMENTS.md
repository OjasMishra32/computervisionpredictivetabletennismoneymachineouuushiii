# Final paper: team requirements (binding for the paper build and integration pass)

1. **Presentation (said many times):** a professional quant research paper - LaTeX, AlgoGators house style (condensed
   display titles, clean sans body at 11 pt, orange-over-black footer rule, COURTSIDE wordmark), journal-grade tables
   (booktabs), numbered vector figures with takeaway captions and "Source:" lines, abstract with JEL codes, references,
   appendix. It must look like the professional quant papers in docs/paper/STYLE_GUIDE.md. Max 5 pages main text at
   11 pt / 1 in (references + appendix after).
2. **Describe everything we did**, compactly, and show the BEST-OPTIMISED version of each component with its best
   honest result, the selection process disclosed next to it (variants tried, walk-forward / pre-registration, deflated
   Sharpe where relevant):
   - the market-structure finding (fast tier, decay, factor-neutral alpha) and v2 (best sizing policy G_50pct_net100);
   - the CV models: table tennis (real held-out footage: precision/recall/lead; the live causal engine numbers), tennis
     (spin-aware tracker, simulated physics: landing error, OUT precision, spin readout), the GPU engine (120 fps, 4.6 ms);
   - the pipeline (WebRTC -> CV -> decision -> order -> network -> venue delay; measured ms; results/e2e, results/webrtc);
   - the CV strategy at feed-latency scenarios (below) and its optimised v3 rule;
   - capital capacity (results/capacity) and financials;
   - every robustness test (cost doubling, blind tests, rigor pack) in one compact table;
   - everything else in an appendix table "Everything we tested" (lens, what it was, best result, verdict).
3. **Latency scenarios (the headline framing), each clearly labelled as an assumed feed (not purchased):**
   | scenario | feed latency | basis |
   |---|---|---|
   | Licensed low-latency feed, best case | **0.5 s** | vendor-stated sub-second betting video (Stats Perform claim; unverified), delivered over WebRTC; plus our measured pipeline |
   | **Base case** | **1.0 s** | licensed feed over WebRTC + our measured pipeline (our WebRTC leg and engine ms from results/webrtc, results/e2e, results/engine) |
   | Requirement / pessimistic | **3.0 s** | the organiser's "< 3 s" bar; sportsbook streams 4-8 s |
   For each: P&L/day, Sharpe, per-share net (IS and OOS), from results/tier0/latency_sweep.json (video_own120; calibrated
   reading 'tournament_lagcal' shown first as the optimised estimate, labelled post hoc; pre-registered 'tournament'
   reading next to it). Plot: returns vs feed latency with dotted vertical lines at 0.5 / 1 / 3 s and the source bands.
4. **Honesty (non-negotiable):** never say we received match video, a licensed feed, live ATP/WTA data, or traded real
   money; every assumed number labelled; IS/OOS separate; failures reported compactly in the robustness table and the
   appendix (track rule: report OOS good or bad, variant counts, peeks). Today's all-points match replay is reported in
   the appendix with its result.

## Addendum after the red team (binding; resolves item 3's ordering)
- Latency-scenario table: show BOTH readings side by side, **pre-registered (2.0 s stamp lag) column first**, then the
  post hoc one-day inference (3.14 s; 95% interval 2.23-3.22 s from results/redteam/) labelled "post hoc estimate";
  never write "calibrated from the data". The high Sharpe values stay visible (that is the optimised estimate), with
  their label and interval next to them. Also state the lag-free requirement: the CV call must land >= ~0.9 s before the
  umpire stamp.
- The sweep's trade set is points the market repriced >= 4c (selected on outcomes, not ex ante): say so in the Table
  caption; report the ex-ante tests (all-points replay; the Markov-leverage selective replay, exploratory) in the
  robustness table and appendix.
- CV: lead with the live causal engine numbers (results/engine/online_vs_offline.json); the offline 11/11 is labelled
  "offline evaluation with a look-ahead feature".
- e2e: our part ~54 ms; 2,119 ms total with a simulated 1 s feed + network + 1 s venue hold, vs the 3,000 ms bar.
- Read derived Q&A numbers from results/redteam/derived.json; run scripts/redteam_acceptance.py before the final commit.

## Addendum (2026-10-04T02:18:17Z): no live/forward results
The live paper session was stopped and the forward test was not run (HYPOTHESIS_V2.md A3). Remove every "pending" slot:
state once, in the rigor/robustness table, "forward test and live paper session: not run (submitted before the forward
window closed)". Do not present any live-session numbers.

## Addendum (2026-10-04T02:59:14Z): forward test reinstated (supersedes the previous addendum for the forward test only)
The blind forward test runs once at 11:30 UTC (HYPOTHESIS_V2.md A4). Keep ONE clean slot for it in the results/rigor
table that fills automatically from results/v2/forward.json (and results/tier0_v3/forward*.json) at build time; until then
it reads "blind forward test: runs 2026-10-04 11:30 UTC (pre-registered)". The live paper session stays out.
