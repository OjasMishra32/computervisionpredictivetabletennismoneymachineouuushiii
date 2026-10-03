# COURTSIDE narrated video: script

Rendered by `scripts/make_video.py` into `results/viz/courtside_video.mp4` (1920x1080, 30 fps, H.264 + AAC)
with captions burned in and a sidecar `results/viz/courtside_video.srt`.

How this file is used:

- Each `## S..` heading is one scene. The `visual:` line describes what is on screen.
- Each line that starts with `>` is one caption and one narration clip (macOS `say`, voice Samantha).
- Words in `{braces}` are filled at render time from results files. The mapping from each name to its
  file and key is in `scripts/make_video.py` (`build_values`) and is written out with every render to
  `results/viz/video_manifest.json`. A result whose file does not exist yet renders as "pending".
- Scene length = narration length + 0.6 s. Scenes are joined with 0.3 s crossfades.

Ground rules for every line: plain English, no hype, every claim true. Tier-0 is always labelled as a
counterfactual. Everything is paper trading. No live ATP/WTA data was used. Failures are shown.

## S01 hook | Call the point before the ball lands
visual: real held-out table-tennis footage (OpenTTGames, CC BY-NC-SA 4.0), the model's MISS call appears before the ball gets there; title card fades out.
> This is a real table tennis rally, from a game our model never saw in training.
> It calls this shot a miss {tt_lead_ms} milliseconds before the ball gets there.
> Courtside asks what that head start is worth on a prediction market, and what we can prove.

## S02 economics | Information arrives in tiers
visual: animated ladder of information tiers after a point ends, each with its measured or assumed delay; cards for who is on the other side and why the gap persists.
> When a point ends, the news spreads in tiers.
> A courtside camera with our vision model would know in about {ldn_ms} milliseconds.
> ESPN's live score trails the order book by about {espn_s} seconds, the public scoreboard by {h4_s}.
> Slower tiers trade against stale prices. The gap persists because speed costs money, and capacity is small.

## S03 evidence | The fast tier wins every month
visual: bars by month, cents per share net of fees: fast-tier wallets (first 3 s), everyone else, and copying the fast tier 3 s later.
> A small group of wallets trades in the first three seconds after a point.
> Thirty seconds later, net of fees, they are up in {ft_pos} of {ft_n} months. Everyone else is down in {oth_neg}.
> Copying them three seconds later loses in {fol_neg} of {ft_n}. The edge goes to whoever is first.

## S04 vision | Calling the point before contact
visual: real held-out test footage with the ball track and the call; panel with precision at 50 ms, its Wilson bound, recall and ball-detection accuracy.
> So we built our own fast tier.
> On held-out games, it tracks the ball and calls misses before contact.
> Fifty milliseconds out, {calls50_phrase}. The 95% lower bound on precision is {wil50} percent.
> It catches {recall50} percent of misses that early, and leaves the rest alone.

## S05 tennis | Tennis replay (simulated physics)
visual: Hawk-Eye-class tennis replay labelled SIMULATED PHYSICS beside a real Polymarket tape; spin readout from the simulation.
> We have no licensed tennis footage, so this replay is simulated physics.
> A {tennis_fps} frame per second tracker calls it out {tennis_lead_ms} milliseconds before the bounce, and reads the spin from the flight.
> On the right is a real Polymarket tape: fast-tier wallets traded within seconds of the point.

## S06 backtest | The backtest, in sample and out
visual: equity curve in sample then out of sample; money counters for capital, end value, Sharpe, max drawdown and win rate with CI; fees-doubled and costs-doubled results.
> Version two trades only at the fast tier's own fill prices, after fees.
> In sample, February to August: {is_c} cents a share, Sharpe {is_sh}, worst drawdown {is_dd} percent.
> Out of sample, a window we had already seen: {oos_c} cents, Sharpe {oos_sh}.
> Double the fees, and out of sample turns negative: {oos_fee2_c} cents.

## S07 overfitting | Deflated Sharpe and overfitting
visual: deflated Sharpe ratio for in sample, out of sample and the blind unseen-market test, at 44 and at all trials; probability of backtest overfitting for two grids.
> We tried thousands of configurations, so we deflate the Sharpe ratio.
> In sample it stays above {dsr_is}, even counting all {n_trials} trials.
> The {oos_days}-day out-of-sample window does not survive that. It falls to {dsr_oos}.
> Probability of backtest overfitting on the 24-variant grid: {pbo24} percent.

## S08 scoreboard | Blind tests and failures
visual: scoreboard of every blind test and stress with PASS / FAIL / NEGATIVE / PENDING chips; count of logged out-of-sample looks.
> Unseen markets passed in sample, then failed out of sample. The market-making variant failed its blind test.
> Table tennis markets had no fast tier at all.
> {forward_sentence} Every look at out-of-sample data is logged: {peeks} entries.

## S09 tier0 | What vision buys (counterfactual)
visual: banner "counterfactual: assumes a licensed live feed + courtside camera (not purchased); parameters measured"; in-sample and out-of-sample cards; P&L per share against reprice timing.
> What does vision buy? This part is a counterfactual.
> It assumes a licensed feed and a courtside camera we did not buy, with parameters we measured.
> In sample, {t0_is_c} cents a share, Sharpe {t0_is_sh}. Out of sample, {t0_oos_c} cents, Sharpe {t0_oos_sh}.
> The sign hinges on how fast the market reprices after the bounce, which we have not measured.
> Under the stamp reading, if that takes less than {t0_be} seconds, the edge is gone.

## S10 live | Live books, paper only
visual: engine on live Polymarket books (paper): message counts, feed latency, zero mismatches, zero orders; live paper session status card.
> The engine runs end to end on live Polymarket order books, paper only.
> In a {live_secs} second check it read {live_msgs} book messages across {live_mkts} markets,
> at a median feed latency of {live_p50} milliseconds, with zero mismatches and zero orders sent.
> {live_sentence}

## S11 risk | Costs, capacity and kill switches
visual: per-day waterfall from gross edge to net after fixed costs; out-of-sample P&L by size; kill-switch table from docs/RISK.md.
> In sample, a gross edge of {gross_day} dollars a day loses {fees_day} to taker fees, leaving {net_day}.
> Central fixed costs, mostly a data licence, are {fixed_day} a day. That leaves {after_day} in sample, and a loss out of sample.
> Out of sample, the edge stays positive only up to about {cap_k} thousand dollars of capital.
> Kill switches stop trading on a drawdown, a stale feed, or a fee change.

## S12 close | Reproduce it
visual: repository URL and the one command; paper-only and data disclaimers; footage credit.
> Everything here is paper trading. No real money was traded, and no live ATP or WTA data was used.
> The code and every result file are in the public repository. One command rebuilds the backtest tables.
