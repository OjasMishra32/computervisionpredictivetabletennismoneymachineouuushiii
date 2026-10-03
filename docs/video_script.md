# COURTSIDE narrated video: script

Rendered by `scripts/make_video.py` into `results/viz/courtside_video.mp4` (1920x1080, 30 fps, H.264 + AAC)
with captions burned in and a sidecar `results/viz/courtside_video.srt`.

How this file is used:

- Each `## S..` heading is one scene. The `visual:` line describes what is on screen.
- Each line that starts with `>` is one caption and one narration clip (macOS `say`, voice Samantha).
- Words in `{braces}` are filled at render time from results files. The mapping from each name to its
  file and key is in `scripts/make_video.py` (`build_values`) and is written out with every render to
  `results/viz/video_manifest.json`. A result whose file does not exist yet renders as "pending".
- Scene length = narration length + 0.6 s, plus a hold on dense scenes (S06, S08, S11: +1.5 s) and the end
  card (S12: +3 s). Scenes are joined with 0.3 s crossfades.

Ground rules for every line: plain English, no hype, every claim true. Tier-0 is always labelled as a
counterfactual. Everything is paper trading. We bought no official ATP/WTA data feed and no trading result uses
one; free public score pages (WTA website, ESPN) were recorded only to time their lag. Failures are shown.
No "tonight", "now" or "tomorrow": dates come from the files, so a render stays true after the forward test.
Verdict words in S08 and S09 are derived from the results files (`s08_sentence`, `t3_sentence`).

## S01 hook | Call the point before the ball lands
visual: real held-out table-tennis footage (OpenTTGames, adapted, CC BY-NC-SA 4.0), the model's MISS call appears before the ball gets there; a note says this is the longest held-out call and gives the median; title card fades out.
> This is a real table tennis rally, from a game our model never saw in training.
> It calls this shot a miss {tt_lead_ms} milliseconds before the ball gets there.
> That is our longest call on held-out games. The median is {lead_med_ms} milliseconds, and it called {lead_n_called} of {lead_n_miss} test misses early.
> Courtside asks what that head start is worth on a prediction market, and what we can prove.

## S02 economics | Information arrives in tiers
visual: the same six-tier ladder as deck slide 2 (ball tracking, umpire, market makers, official feed, TV and public scores, streams), each with its measured, inferred or assumed delay; cards for who is on the other side and why the gap persists.
> When a point ends, the news spreads in tiers.
> Ball tracking knows before the bounce. Our vision model takes about {vis_ms} milliseconds per call in a laptop benchmark; we have no courtside camera.
> Market makers reprice about {book_vs_stamp_s} the official point stamp. ESPN's live score trails the book by about {espn_s} seconds.
> Slower tiers trade against stale prices. The gap persists because speed costs money, and capacity is small.

## S03 evidence | The fast tier wins every month
visual: bars by month (walk-forward, in sample then out of sample in pale), cents per share net of fees: fast-tier wallets (first 3 s), everyone else, and copying the fast tier 3 s later.
> A small group of wallets trades in the first three seconds after a point.
> Thirty seconds later, net of fees, they are up in {ft_pos} of {ft_n} months, including {ft_pos_oos} of {ft_n_oos} out of sample. Everyone else is down in {oth_neg}.
> Copying them three seconds later loses in {fol_neg} of {ft_n}. The edge goes to whoever is first.

## S04 vision | Calling the point before contact
visual: real held-out test footage with the ball track and the call; panel with precision at 50 ms, its Wilson bound, recall and ball-detection accuracy on the held-out test frames.
> So we tested whether vision could get there.
> On held-out table tennis games, it tracks the ball and calls misses before contact.
> Fifty milliseconds out, {calls50_phrase}. The 95% lower bound on precision is {wil50} percent.
> It catches {recall50} percent of misses that early, and leaves the rest alone.

## S05 tennis | Tennis replay (simulated physics)
visual: Hawk-Eye-class tennis replay labelled SIMULATED PHYSICS beside a real Polymarket tape; spin readout from the simulation.
> We have no licensed tennis footage, so this replay is simulated physics.
> In simulation, a {tennis_fps} frame per second tracker calls it out {tennis_lead_ms} milliseconds before the bounce, and reads the spin from the flight.
> On the right is a real Polymarket tape: fast-tier wallets traded within seconds of the point.

## S06 backtest | The backtest, in sample and out
visual: equity curve in sample then out of sample; money counters for capital, end value, Sharpe, max drawdown and win rate with CI; fees-doubled and costs-doubled results.
> Version two trades only at the fast tier's own fill prices, after fees.
> In sample, February to August: {is_c} cents a share, Sharpe {is_sh}, worst drawdown {is_dd} percent.
> Out of sample, a window we had already seen: {oos_c} cents, Sharpe {oos_sh}.
> Double the fees, and out of sample turns negative: {oos_fee2_c} cents.

## S07 overfitting | Deflated Sharpe and overfitting
visual: deflated Sharpe ratio (3 dp) for in sample, out of sample and the blind unseen-market test, at 44 and at all trials; probability of backtest overfitting on the 24-variant grid by Sharpe and by our selection rule, and on the sizing grid.
> We tried thousands of configurations, so we deflate the Sharpe ratio.
> In sample it is {dsr_is}, even counting all {n_trials} trials.
> The {oos_days}-day out-of-sample window does not survive that. It falls to {dsr_oos}.
> Probability of backtest overfitting on the 24-variant grid: {pbo24} percent picking by Sharpe, {pbo24_sel} percent with our own selection rule.

## S08 scoreboard | Blind tests and failures
visual: scoreboard of every blind test and stress with PASS / FAIL / NEGATIVE / PENDING chips, including v1's held-out loss and the frozen tier-0 v3 blind tests (counterfactual); count of logged out-of-sample looks at render time.
> {s08_sentence}
> {s08_sentence2}
> {forward_sentence} Every look at out-of-sample data is logged: {peeks} entries at render time.

## S09 tier0 | What vision buys (counterfactual)
visual: banner "counterfactual: assumes a licensed live feed + courtside camera (not purchased); parameters measured"; in-sample and out-of-sample cards; P&L per share against reprice timing; the frozen v3 blind-test failure.
> What does vision buy? This part is a counterfactual.
> It assumes a licensed feed and a courtside camera we did not buy, with parameters we measured.
> In sample, {t0_is_c} cents a share, Sharpe {t0_is_sh}. Out of sample, {t0_oos_c} cents, Sharpe {t0_oos_sh}.
> The sign hinges on how fast the market reprices after the bounce, which we have not measured.
> Under the stamp reading, if that takes less than {t0_be} seconds, the edge is gone. {t0_pre_sentence}
> {t3_sentence}

## S10 live | Live books, paper only
visual: market data on live Polymarket books (paper): message counts, feed latency, mismatches, orders; live paper session card with its date and state (warming up / running / stopped / finished).
> The market-data and paper-trading legs run on live Polymarket order books, paper only.
> In a {live_secs} second check it read {live_msgs} book messages across {live_mkts} markets,
> at a median feed latency of {live_p50} milliseconds, with {live_mismatch} mismatches and {live_orders} orders sent.
> The full chain, from vision call to paper order, ran on a recorded book. {live_sentence}

## S11 risk | Costs, capacity and kill switches
visual: per-day waterfall from gross edge to net after fixed costs; out-of-sample P&L by size; kill-switch table from docs/RISK.md.
> In sample, a gross edge of {gross_day} dollars a day loses {fees_day} to taker fees, leaving {net_day}.
> Central fixed costs, mostly a data licence, are {fixed_day} a day. That leaves {after_day} in sample, and a loss out of sample.
> Before fixed costs, out of sample is still positive at {cap_k} thousand dollars of capital, and negative by {cap_neg_k} thousand.
> Kill switches stop trading on a drawdown, a stale feed, or a fee change.

## S12 close | Reproduce it
visual: repository URL; the replay and reproduce commands with honest times; note that the vision calls need the frozen model (not in git); paper-only and data disclaimers; manifest pointer; footage credit.
> Everything here is paper trading. No real money was traded.
> We bought no official ATP or WTA data feed, and no trading result uses one. Free public score pages were recorded only to time their lag.
> The code is public. One command replays the paper engine on recorded books in seconds. Two more rebuild every table from public data, in one to two hours.
> Every number in this video is listed with its source file in the video manifest.
