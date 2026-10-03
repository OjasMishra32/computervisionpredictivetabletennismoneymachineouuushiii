# COURTSIDE — Devpost submission text

**Tagline:** Who gets paid in the seconds after a tennis point, and what it takes to be first.

## Inspiration
In-play tennis markets on Polymarket jump at every point. We asked a trader's question: when the
price moves, who is on the other side, and why are they losing? Tennis has a clean information
ladder. Ball tracking sees the result before the ball lands, the umpire at the bounce, data feeds a
second later, and streams tens of seconds later. That makes it a natural lab for latency.

## What it does
- Measures, on **13,084 resolved ATP/WTA matches ($2.84B traded)**, who makes and who loses money in
  each second after a point, from Polymarket's public trade tapes. Every print is classified by side
  and every fee is the match's own.
- Finds a **persistent fast tier**: wallets that trade within 3 s of a point and beat the market in
  **11 of 11 months**, selected walk-forward. Everyone else loses ~1¢/share, and copying the fast tier
  3 s later loses too.
- Turns that edge into a strategy (**v2**: risk-parity sizing, fee-aware wallet filter, 100-share net
  cap, hold to resolution). In sample it earns **+1.38¢/share, Sharpe 14.5, max drawdown −2.0%, 7/7
  months**, and stays positive in every month at a full tick of slippage. Out of sample it earns
  +0.60¢ [0.09, 1.13] at front-of-queue prices.
- Measures latency live: the book reprices **1.2 s before the official point timestamp**. ESPN,
  Polymarket's own score feed and the WTA API are 27–43 s behind, and Kalshi leads Polymarket by ~2 s.
- Shows how early ball tracking can call the point. A Hawk-Eye-class physics model gives a ±2.4 cm
  landing call 100 ms before the bounce. Real 120 fps footage, run on HiPerGator, called misses 50 ms
  before contact, 11/11 correct, and there are demo clips.

## How we built it
Python on public Polymarket and Kalshi APIs (no keys); an exact point-level tennis Markov model; a
live websocket recorder for order books and four score feeds; a replay engine that makes paper orders
wait the venue's delay plus our measured network latency; ball tracking on HiPerGator GPUs (OpenTTGames
with BlurBall weights, TrackNet tennis); and a six-lens optimisation workflow where every claimed
improvement was attacked by two independent verifier agents before it could enter v2.

## Challenges
Being honest with ourselves. Five of our ideas failed and are in the note: chasing the move,
favourite bias, maker exits, side-market sniping, and copying Kalshi. A verifier caught hindsight in
our first v2 draft: 81% of its out-of-sample P&L came from trades made before our detector could have
fired. We fixed it, re-ran everything on a causal window, and pre-registered a blind forward test
before the window opened.

## What we learned
In today's regime (1 s order delay, 5% fee, ~130 competing wallets) the edge is real but smaller than
one price tick. It pays only whoever is first to the stale quote. You cannot get there remotely:
public data is the slow tier. In-venue, high-frame-rate tracking plus a gateway co-located with the
matching engine (measured: Cloudflare's Miami edge, with an origin consistent with London) is what
moves you up the ladder.

## Integrity
`HYPOTHESIS.md` was committed before any result. The out-of-sample period was opened once and logged.
v2 and its forward test were pre-registered before the window opened (`HYPOTHESIS_V2.md`), and every
change is listed in `DEVIATIONS.md`. One command (`bash reproduce.sh`) regenerates every number. The
code only reads public data and never places an order.

## Built with
python · pandas · numpy · scipy · matplotlib · websockets · Polymarket CLOB/Gamma/Data APIs · Kalshi
API · HiPerGator (SLURM, L4 GPUs) · PyTorch · OpenCV · ffmpeg

## Links
Repo: https://github.com/OjasMishra32/courtside · Quant note: `docs/NOTE.pdf` · Demo videos:
`results/viz/courtside_replay.mp4`, `results/tracking/demo/supercut.mp4`
