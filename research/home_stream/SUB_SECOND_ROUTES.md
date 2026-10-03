# Sub-second video: every route to ≤ 1 s, and how to present it

Merged from five read-only web sweeps run on 2026-10-03: webrtc-platforms, betting-video, tt-leagues, public-ll and
venue-legal. A few key figures were re-fetched today to check them; those are marked **[checked]**. No accounts were
created, nothing was bought and no forms were submitted. Machine-readable copy: `results/home_stream/sub_second_routes.json`.

Notation. **M** is a measured figure (an independent test, or our own measurement). **C** is a vendor or platform
claim. **I** is internal to this repo. Glass-to-glass (g2g) runs from the moment light hits the camera to the
moment the frame is on the viewer's screen. Player-side stats on Twitch and YouTube count only from the
broadcaster's encoder, so they understate g2g. Quotes are at most 15 words. A claim with no source says
"no public source; assumption".

**Goal.** Get live video of a Polymarket-listed tennis or table-tennis match with g2g ≤ 1 s, so CV can call the
point before the book reprices. On the official WTA clock, the book reprices a median 1.16 s **before** the
umpire stamp (n = 482 points, I: `research/v2/latency/RESULTS.md`), which is roughly 0.7–1.35 s after the
bounce (inference; the stamp lag is unmeasured). After that, our taker order still waits the 1 s venue delay.

---

## 1. Ranked routes

Ranking: legal and eligible for us first, then usable tonight, then latency, then cost. Band A holds every route
that reaches ≤ 1 s, whether measured or only claimed. Band B holds the best routes at 1–3 s. Band C holds slower
public routes, listed for scale.

### Band A: routes to ≤ 1 s

| # | route | what we get | latency (M / C) | cost | legal / eligible for us | usable tonight? | path to obtain |
|---|---|---|---|---|---|---|---|
| A1 | **Self-hosted WebRTC on our own camera**: OBS ≥ 30 (WHIP) into MediaMTX or Broadcast Box, WHEP viewer or CV process | our own footage only (a rally on our table, a tennis hit) | **M: 42 ms local** (OBS WHIP to Broadcast Box) [S1, checked]; **M: 130 ms local, 170 ms remote** [S4, checked]; **M: MediaMTX p50 180 ms / p95 240 ms LAN, 310–740 ms p50 in three other deployments** [S3, checked]; M: about 0.4 s via the public Broadcast Box server [S2] | $0 (open source; licences not checked, assumption) | **yes**: our own footage | **yes** | install OBS + MediaMTX locally and measure ourselves (method in §4.4) |
| A1b | Camera straight into the CV process, no streaming hop | same, minus the network leg | M: about 100 ms of the 130 ms local total is "camera + USB" [S4, checked]; at 120 fps one frame is 8.3 ms (I: `results/decay/decay.json`) | $0 | yes | **yes** | the floor for any route; this is how `engine/vision` already runs |
| A2 | Cloudflare Stream WebRTC (WHIP/WHEP, now GA) | our own footage, relayed through a CDN | C: "less than 500 milliseconds of latency" [S7, checked] | $1 per 1,000 min delivered; **billing starts 2026-10-15**, so free tonight (inference from the billing date) | yes; needs a Cloudflare account, not a betting account | yes, after the user signs up | user creates the account; WHIP from OBS |
| A3 | Amazon IVS Real-Time | our own footage | C: under 300 ms [S8b] | $0.072 per participant-hour; new accounts get "20 participant hours per month" for 12 months [S8, checked] | yes; needs an AWS account | yes, after sign-up | user creates the account |
| A4 | Red5 Cloud | our own footage | C: under 250 ms [S9] | 50 GB/month free, no card (C) [S9] | yes; account | yes, after sign-up | user creates the account |
| A5 | Phenix | our own footage. Phenix lists betting-video suppliers (SIS "Watch & Bet", RMG) as customers | C: "< 1/2 second of latency" [S10, checked] | free trial (terms not shown) [S10] | yes for our own content | yes, after a trial sign-up | user requests the trial |
| A6 | Agora Interactive Live Streaming, Premium tier | our own footage | C: 400–800 ms Premium, 1.5–2 s Standard (search snippet; the docs page returned 404) [S11] | first 10,000 min/month free [S11] | yes; account | yes, after sign-up | user creates the account |
| A7 | nanocosmos nanoStream (H5Live / MoQ) | our own footage; vendor serves iGaming and live casino | C: under 1 s camera to viewer [S12] | "free start" offered; rates unknown | yes; account | yes, after sign-up | user creates the account |
| A8 | **Organiser-consented camera or raw contribution feed at a private table-tennis league** (TT Elite Series, Czech Liga Pro, TT Cup) | a real Polymarket-listed match | physics as in A1 plus venue to London 14–50 ms one way [S4]: **about 0.15–0.5 s g2g** (inference from S3/S4); SRT contribution adds a 120 ms default receive buffer [S16] | no public source (price unknown) | **legal only with written consent** from the rights holder. TT Elite Series names Sportradar as its "technology partner" [S23], so exclusivity is possible (assumption). Setka Cup is ruled out: BETER says "Only three people can be present in a room" [S24] | **no** | email the organiser for research or academic access to their raw feed (SRT/WebRTC) or to a camera position. This is the **only legal ≤ 1 s route to a real Polymarket match** we found |
| A9 | B2B betting video sold to licensed sportsbooks: Sportradar/Betradar streams (now including the ex-IMG Arena portfolio [S31]), Stats Perform (in the US via Sports Content Co.), BETER (Setka Cup) | real ATP, Challenger, WTA, Grand Slam and table-tennis video | **no absolute g2g figure published.** C: Sportradar says "eight seconds faster than any TV signal", which is relative to TV [S30]. Stats Perform's WTA page gives no video latency [S34, checked]. The betting-video sweep reported a "sub-second video" claim on Stats Perform's delivery platform, but its URL was lost in the merge, so treat it as unverified | third-party estimate "$10,000+/month" [S32]; no public price | **not eligible**: video is for "licensed sportsbooks" [S34, checked]; no research licence published | **no** | operator contract only |
| A10 | Spectator's own camera at an ATP, Challenger, WTA, ITF or WTT event | a real match | physically about 110–170 ms g2g [S4] | ticket | **no.** Ticket terms ban use "including betting or gambling or prediction markets activity" (US Open, search snippet) [S38]. ITF regulations XI.B bar collecting or transmitting Tournament Data [S37]. WTT ticket policy 6.2/6.3/9.1 bans recording and "Court-siding" [S39]. 20 spectators were caught at the 2016 US Open [S40]. Fails the hackathon ToS rule | no | none (excluded) |
| A11 | Student media accreditation | press access, no feed rights | n/a | n/a | **no.** Monte-Carlo's media charter bans "any form of gambling or betting activity whatsoever" [S41]. Accredited media are Covered Persons under the ITF code [S37] | no | none (excluded) |

### Band B: best routes at 1–3 s

| # | route | what we get | latency (M / C) | cost | legal / eligible for us | usable tonight? | path to obtain |
|---|---|---|---|---|---|---|---|
| B1 | Managed WebRTC, WebSocket and HESP CDNs under real network conditions (Streaming Media test, Oct 2023, vendors anonymised) | our own footage | **M** on a normal network: WebRTC 0.58 s and 1.07 s (two vendors), WebSockets 0.97 s and 1.17 s, HESP 1.12 s. On 5G: 0.69–1.63 s. **On 4G: 1.78–2.34 s** [S5, checked]. Measured with a burnt-in wall clock and a 1/500 s camera | varies | yes | yes, after sign-up | the cell uplink, not the protocol, decides whether we stay under 1 s |
| B2 | **Polymarket in-app ATP and Challenger streams** (supplied by TDI) | real ATP/Challenger video; no WTA, ITF or table tennis | **no public source** | assumption: free to registered users | US only, inside the CFTC-regulated Polymarket US app. "Registered Polymarket users in the U.S. can watch live ATP matches" [S29]. KYC needs a US address, ID and SSN (third-party guide) [S29c]. Whether an unfunded account can watch: no public source. Whether screen capture into CV is allowed: no public source | **maybe**, only if a team member already has an unfunded Polymarket US account and the terms allow capture | read the Polymarket US terms first; then measure latency against the book |
| B3 | Twitch Low Latency (for example the "Challenger_Series" channel; not confirmed to be the Polymarket-listed TT Challenger) | free public video | C: "about 2-4 seconds" (third party) [S21]; Twitch "down to 3 seconds", "1.5 seconds in certain cases" in Korea (search-result quote; page did not load) [S21b]. Encoder to player, not g2g | free | viewing yes; CV on captured frames is a ToS risk | only if the channel is live (snippet: next stream Thursday 06:30 UTC) [S22] | the player shows "Latency to Broadcaster" in Advanced video stats |
| B4 | YouTube Ultra-low latency: Setka Cup Live, TT Elite Series, WTT (China Smash, 1–11 Oct) | free public video of Polymarket-listed table tennis | C: Ultra-low "latency less than 5 seconds", Low "less than 10 seconds" [S17, checked]; 2–5 s (third-party FAQ) [S18]; M: 3–4 s by ear on one blogger's own stream [S19]. Whether these channels use ULL: unknown | free | viewing allowed for "personal, non-commercial use"; ToS bans access "using any automated means" [S20]. WTT may be geo-blocked in the US; do not use a VPN [S26] | **yes** (Setka is live 24/7 [S25]) | watch only; no automated capture |
| B5 | Fast scout data, not video: Stats Perform RunningBall, Sportradar/TDI umpire-chair data | point events | C: RunningBall is "32% of points more than 1 second faster" than the umpire feed [S34, checked]; Sportradar's "Low" band is "~0–<4 seconds" [S33] | no public price | operators only | no | operator contract |

### Band C: slower public routes, for scale

| # | route | latency | note |
|---|---|---|---|
| C1 | **Setka Cup's own public Flussonic server** (`nl.stream.setka-cup.com/<arena>/public/…`), including the **WebRTC (WHEP) output its embed player uses** | **M (preliminary, I), arena "granite", 25–30 s runs, 2026-10-03 20:30–20:40 UTC, burned-in arena clock:** **WebRTC median 12.23 s** (p5–p95 12.15–12.42, n = 22); LL-HLS median 12.97 s (n = 26; 0.4 s CMAF parts arriving every 0.38 s, so at the live edge); classic HLS 19.41 s (n = 40); the same arena on YouTube 20.19 s (n = 19). Tool: `research/home_stream/probe_latency.py`; output not committed; full run pending | Even WebRTC, a sub-second transport, sits **about 12 s** behind the on-screen clock, and transport choice moves it by under 1 s (WebRTC against LL-HLS: −0.74 s). So the ~12 s is added **upstream** of the CDN: by the production chain, by a deliberate delay on the public feed (assumption, no public source), or by the production PC's clock being offset. These three are not yet separated. One way to separate them is to compare the video against Setka's own score timestamps or the Polymarket book for the same points. Setka's terms on automated access were not checked |
| C2 | LL-HLS and LL-DASH, generic | M: LL-HLS 18.91 s on a normal network in one test [S5, checked], against C: 2–3 s (Wowza) [S14]; M: LL-DASH 5.11 s tuned, 7.27 s default [S15] | the in-repo Setka LL-HLS figure (C1, about 13 s) is nowhere near the 2–3 s claim |
| C3 | FanDuel TV / TV+ (WTT's US rights holder, free) | no public source. For scale, OTT apps measured from inside the Super Bowl stadium ran 26–78 s behind (M, by Phenix, a vendor) [S28] | |
| C4 | Public score data (not video) | M (I): ESPN game +27.5 s, Polymarket sports websocket +29.1 s, WTA public API point +43.3 s, all relative to the official stamp; 0 of 295 changes led the book by more than 1.3 s | `research/v2/latency/RESULTS.md` |
| C5 | WTT official live scores (Confluent pipeline) | C: the goal is "within the milliseconds" (an interview statement, not a measurement) [S27] | this is the umpire's stamp itself, which in tennis comes after the book reprices |

**Correction to the webrtc-platforms sweep.** That sweep reported "WebRTC 0.58 s / 0.69 s 5G / 2.34 s 4G" as a
protocol baseline. When re-fetched, that row turned out to be **one** WebRTC vendor (the one with TURN). The other
WebRTC vendor measured 1.07 s / 1.30 s / 2.20 s. Averaged over the three networks, WebRTC came to 1.25–1.30 s
[S5, checked]. Managed WebRTC is therefore **not** reliably under 1 s over the public internet. Only the local and
LAN figures (A1) are.

---

## 2. Bottom line

**Is ≤ 1 s achievable tonight from home on a Polymarket-listed match? No.**

1. **Measured, not just inferred.** Setka Cup's own Flussonic server has a public WebRTC (WHEP) output, which its embed
   player uses. It is the only public WebRTC feed of a Polymarket-listed match we found. Our
   preliminary probe puts that WebRTC feed a median **12.2 s** behind the burned-in arena clock. LL-HLS was 13.0 s,
   HLS 19.4 s and YouTube 20.2 s (C1). The transport is not the bottleneck: about 12 s is added before the CDN, unless
   the arena clock itself is offset (C1). Other public streams claim YouTube ULL at under 5 s
   (C) or Twitch LL at 2–4 s (C), which is still far above 1 s.
2. Every sub-second route to real match video falls into one of two kinds:
   - a B2B betting feed sold only to licensed sportsbooks (A9), whose latency is unpublished anyway;
   - a camera in the venue. At ATP, WTA, ITF and WTT events that is banned for betting and prediction-market use
     (A10, A11). At a private table-tennis league it needs written consent we do not have (A8).
3. The one rights-holder stream tied to a prediction market, Polymarket's in-app ATP stream (B2), needs a KYC'd US
   exchange account, and its latency is unpublished.

**Is ≤ 1 s achievable tonight from home on our own footage? Yes, for $0.** Self-hosted WebRTC (A1) has been
measured by others at 42 ms locally and 180 ms p50 on a LAN. We should measure our own pipeline tonight (§4.4) and
quote that number.

**Cheapest legal path to ≤ 1 s:**
- *For the demo or video:* A1, $0, tonight, on our own camera.
- *For a real Polymarket match:* A8, written consent from a private table-tennis rights holder (TT Elite Series,
  Czech Liga Pro or TT Cup) for their raw contribution feed or a camera position. The price is unknown (no public
  source). The only alternative is a sportsbook B2B licence (A9), which we are not eligible for (third-party
  estimate $10k+/month).

**Even ≤ 1 s does not win the race.** In our backtest the break-even video delay is **1.09 s in sample and 1.01 s
out of sample** under the headline timing reading. Under the calibrated reading it is **0.34 s / 0.30 s**. A 1 s
feed sits at break-even, and only the courtside camera (V ≈ 0) is clearly positive. Details in §4.2.

Also note that the international Polymarket docs list the US and UK as close-only (no new positions) [S42]. This
changes nothing here, since we place no orders. It does mean any live-trading claim would be false twice over.

---

## 3. Latency budget for the best route

Best route to a real match: an organiser-consented 120 fps camera at the venue, WebRTC to a London box running our
CV, and a London gateway to Polymarket (eu-west-2 [S42]). This is A8, not available tonight.

| leg | value | type | source |
|---|---|---|---|
| bounce → frame captured | 0–8.3 ms at 120 fps; about 100 ms through a USB webcam pipeline | M | I `results/decay/decay.json` (camera_s); S4 |
| encode | about 10 ms | M | S4 |
| venue → London network | Europe 10 ms … Asia 100 ms (model assumption); 14–50 ms one way to London | assumption / M | I tier-0 §8 item 9; S4 |
| jitter buffer + decode | about 10 ms decode; **g2g total 130–170 ms (one test), p50 180 ms LAN, 520 ms cross-region** | M | S4, S3 |
| **video subtotal (g2g)** | **about 0.13–0.52 s** | M | |
| CV inference | 20 ms assumed in the tier-0 model; **84 ms p50 / 127 ms p90 measured** on a laptop M4 (stand-in classifier); out-calls can come 25–100 ms *before* the event | assumption / M (I) | I `results/decay/decay.json` cv_measured_s; `research/v2/tier0_v3/RESULTS.md` |
| our order → matching engine | 2 ms from London; 67 ms from Florida | M (I) | I `results/decay/decay.json` |
| venue delay (marketable orders) | **1.000 s.** Polymarket only says the order "waits for the market's configured delay window"; the duration comes from the tapes | M (tapes) / docs | S43, checked; I tier-0 |
| **order can match at** | **about 1.15–1.7 s after the bounce** | | sum |
| book reprice | t_reprice − t_bounce is **unmeasured**: 0.68 s under the stamp-noise reading, 1.35 s under the calibrated inference. R = −1.16 s median against the stamp. Stale depth is gone 0.5 s after the reprice | M (R) / inference | I `research/v2/latency/RESULTS.md`, `research/v2/tier0/RESULTS.md` §2 |

```
t after bounce (s) 0.0       0.5       1.0       1.5       2.0       2.5
                   |----+----|----+----|----+----|----+----|----+----|
book reprices                    RRRRRRRRRRRRRrrrrrrrrrr             | R = reprice lands in 0.68-1.35 s (unmeasured)
                                                                     | r = stale depth still resting (gone 0.5 s after R)
A venue cam+WebRTC ggggcDDDDDDDDDDDDDDDDDDDD                         | matchable at ~1.27 s  (g2g 0.18 + CV 0.08 + 1 s)
B 0.5 s video feed ggggggggggccDDDDDDDDDDDDDDDDDDDD                  | matchable at ~1.59 s
C 1.0 s video feed ggggggggggggggggggggccDDDDDDDDDDDDDDDDDDDD        | matchable at ~2.09 s
D public YouTube ULL (3-5 s)  ......................................>| matchable at >= 4.1 s (off chart)
E Setka public WebRTC (12.2 s, prelim) ..............................>| matchable at ~13.3 s (off chart)

g = glass-to-glass video   c = CV inference (84 ms p50)   D = 1 s venue delay   (London gateway: 2 ms, invisible)
```

How to read it. Route A lands inside the reprice band: it wins only when the book is slow (the 1.35 s reading).
Route B lands after the whole reprice band. It is still inside the stale-depth window under the slow reading,
but not under the fast one. Route C lands after everything.
The sweep also found that a third of reprices land 50–100 ms after a whole UTC second, which fits a venue that
releases delayed orders on a 1 s clock. That is not verified. If true, sub-second gains are quantised
(I `results/tier0/latency_sweep.json` timing_diagnostics).

---

## 4. How to present it

### 4.1 What we can and cannot say

**Can say:**
- We measured our own camera → WebRTC → CV pipeline at **[X] ms g2g**, on our own footage.
- We simulated a 1 s and a 0.5 s video feed as an **assumed-data scenario**.
- Sub-second video of these matches exists only as licensed sportsbook feeds, or as a camera at the venue with the
  organiser's consent.
- The fastest public feed of a Polymarket-listed match we found, Setka Cup's own WebRTC stream, measured a median
  12.2 s behind the on-screen arena clock in a preliminary test (C1). Say "preliminary" until the full run lands.

**Cannot say:**
- that we received live video of any Polymarket match at ≤ 1 s, or at any latency, into CV;
- "real-time match feed", "sub-second match stream", "we traded" or "live P&L";
- "WebRTC is sub-second" without the qualifier (normal network: 0.58–1.07 s; 4G: 2.2–2.3 s);
- any vendor claim from §1 as if it were a measurement;
- that a 1 s feed is profitable. It is at break-even.

### 4.2 Numbers to cite (tier-0 sweep, own 120 fps CV, headline per-tournament timing reading, 20 seeds)

Source: `results/tier0/latency_sweep.json` and `.csv`. The model is `scripts/tier0_latency_sweep.py`. These files
were regenerated at 2026-10-03 16:39 EDT; the cited values are unchanged from the 16:23 run. They were **not yet
committed** when this file was written, and the doc `research/v2/tier0/LATENCY_SWEEP.md` is still to come.
The V = 0 row reproduces the published tier-0 headline exactly. The OOS period is burned, not blind.

| video delay V | IS c/share [95 % CI] | IS $/day ± SD | burned OOS c/share [CI] | OOS $/day ± SD |
|---|---|---|---|---|
| 0 (courtside camera, not feasible) | +1.10 [0.82, 1.38] | $88.8 ± 21.3 | +0.58 [−0.08, 1.21] | $46.4 ± 39.0 |
| **0.5 s** | **+0.61 [0.08, 1.14]** | **$28.4 ± 19.0** | −0.02 [−1.22, 1.09] | $15.2 ± 36.0 |
| **1.0 s** | **+0.40 [−0.32, 1.08]** | **$14.8 ± 14.7** | −0.38 [−2.08, 1.20] | $4.3 ± 29.6 |

- **Break-even V:** 1.09 s IS and 1.01 s OOS (seed-mean curve). The per-share CI stays above 0 only for V < 0.65 s
  (IS). OOS never excludes 0.
- **Pessimistic CV** (no early calls, 50 ms inference; betting video runs at 25–50 fps): 0.5 s gives IS +0.55c
  [0.01, 1.07] at $26/day and OOS −0.16c at $10/day. 1.0 s gives IS +0.15c [−0.68, 0.92] at $8/day and OOS −1.18c
  at −$13/day.
- **Stamp-noise reading** (reprice 0.68 s after the bounce): loses at every V, including V = 0 (IS −$30/day; −$17/day
  for V ≥ 0.25 s).
- **Calibrated reading** (1.35 s, an inference): V = 0.25 s gives IS $188/day. V = 0.5 s gives IS −$45/day.
  Break-even is 0.34 s IS and 0.30 s OOS.

### 4.3 Exact wording

**Paper, methods paragraph:**

> **Video-feed scenarios (counterfactual with assumed data).** We did not receive live video of any
> Polymarket-listed match. We have no licensed feed and no camera at any venue, and no live ATP/WTA data was
> used. To ask what a fast video feed would be worth, we rerun the verified tier-0 model with our CV calls delayed
> by a video latency V. The model uses real Polymarket tapes, fees and 1 s venue delays, with timing and fills
> parameterised from our own measurements. We report V = 1.0 s and V = 0.5 s. A feed in this range is what WebRTC
> delivers in independent glass-to-glass tests: 0.58–1.07 s on a normal network and 2.2–2.3 s on 4G (Streaming
> Media, Oct 2023). For these matches, feeds this fast are sold only to licensed sportsbooks (Sportradar, Stats
> Perform, BETER), or would need a camera at the venue with the organiser's written consent. We have neither.
> The fastest public feed of a Polymarket-listed match we found, Setka Cup's own WebRTC stream, ran a median
> 12.2 s behind the on-screen arena clock in a preliminary test. The only sub-second pipeline we ran is our own
> camera → WebRTC → CV on our own footage, measured at [X] ms.

**Paper, results paragraph:**

> With a 1.0 s video feed the strategy is at break-even: +0.40¢/share [−0.32, 1.08] and $15 ± 15/day in sample,
> −0.38¢ [−2.08, 1.20] and $4 ± 30/day on the burned out-of-sample period. With a 0.5 s feed it earns +0.61¢
> [0.08, 1.14] and $28 ± 19/day in sample, but is not distinguishable from zero out of sample (−0.02¢ [−1.22,
> 1.09]). The break-even video delay is 1.09 s (IS) and 1.01 s (OOS) under our headline timing reading. If the
> book reprices 0.68 s after the bounce, the strategy loses at every delay, a courtside camera included. Under our
> calibrated inference (1.35 s) the feed must be under about 0.3 s. Because the venue's 1 s order delay comes on
> top of the feed, video speed is necessary but not sufficient.

**Deck slide** (title, then bullets, then footnote):

> **What a 1-second video feed would be worth (assumed data)**
> - Courtside camera (V = 0): +$89/day in sample, +$46/day out of sample
> - 0.5 s feed: +$28/day in sample (CI just above 0); not significant out of sample
> - 1.0 s feed: break-even (+$15/day IS, +$4/day OOS, both CIs include 0)
> - Sub-second video of these matches is sold only to licensed sportsbooks. We did not buy it.
> - Our own camera → WebRTC → CV: [X] ms, measured on our footage
>
> *Footnote: Counterfactual with assumed data: licensed feed/video not purchased; parameters measured.
> results/tier0/latency_sweep.csv. WebRTC g2g: Streaming Media, Oct 2023.*

**Video narration** (about 20 s):

> "From home, we can't legally get live video of these matches in under a second. The fastest public feed we
> found ran about twelve seconds behind the arena clock in a preliminary test. Feeds under a second go only to
> licensed sportsbooks, or come from a camera at the venue. So we measured our own pipeline instead: our camera,
> over WebRTC, into our model, in [X] milliseconds. Then we asked the backtest what a one-second feed would be
> worth. The answer is break-even. At half a second it's positive in sample but not out of sample. This is a
> simulation with assumed data, not a live result."

**On-screen caption:** `ASSUMED-DATA SCENARIO · 1 s / 0.5 s match video not purchased · own-footage WebRTC latency measured`

### 4.4 Measuring our own [X] tonight (A1, $0)

1. Put a millisecond counter on a high-refresh screen in the camera's view.
2. Stream it: OBS ≥ 30 (WHIP output) into a local MediaMTX (or Broadcast Box), then view it in a browser over WHEP.
   Optionally, also send it through Cloudflare Stream WebRTC (A2), which is free until 2026-10-15, to get a
   remote-path figure.
3. Film the source counter and the viewer screen together with a 240 fps phone, and read about 200 frame pairs
   [S3 method]. An alternative is to reuse the burned-in-clock method of `probe_latency.py`, with an NTP-synced
   clock overlay.
4. Report p50 and p95, and say whether the figure is LAN or remote. Add the CV leg from
   `results/decay/decay.json` (84 ms p50) for the "camera → call" number.

### 4.5 Compliance flags for in-repo work

- `research/home_stream/probe_latency.py --source youtube` pulls the stream with `yt-dlp`. That is automated access,
  which YouTube's ToS prohibits ("using any automated means") [S20]. Measure YouTube by watching and reading the
  player instead, or drop that source.
- A YouTube run has already been made (preliminary result in C1). Before citing it, either re-measure by watching or
  drop it.
- The Setka Flussonic probe (C1: HLS, LL-HLS, WebRTC/WHEP) decodes a public endpoint automatically. Setka's terms
  were not checked, so check them before running it at length or citing it as more than a preliminary
  measurement.

---

## Sources

[checked] means re-fetched on 2026-10-03 for this merge. All other entries are as reported by the sweeps.

| id | URL | short quote or note |
|---|---|---|
| S1 | https://webrtchacks.com/webrtc-cracks-the-whip-on-obs/ | "glass-to-glass latency was only 42 ms" [checked] |
| S2 | https://gigazine.net/gsc_news/en/20260117-broadcast-box-webrtc/ | about 0.4 s via the public Broadcast Box server (sweep paraphrase) |
| S3 | https://www.adaptnxt.com/blogs/mediamtx-whip-whep-latency-benchmarks-4-deployments | p50/p95 180/240 ms LAN; 310/480, 520/890, 740/1,180 ms; method: "240 fps phone camera" [checked] |
| S4 | https://transitiverobotics.com/blog/webrtc-latency-breakdown/ | local 130 ms, remote 170 ms; camera + USB about 100 ms [checked] |
| S5 | https://www.streamingmedia.com/Producer/Articles/Editorial/Featured-Articles/Glass-to-Glass-Report-Comparing-Low-Latency-Streaming-Providers-161238.aspx | per-network table, Oct 2023; method: "a burnt-in wall clock in the top right corner" [checked] |
| S6 | https://www.rfc-editor.org/rfc/rfc9725.html | WHIP standardised as RFC 9725, March 2025 |
| S7 | https://developers.cloudflare.com/stream/webrtc-beta/ | "less than 500 milliseconds of latency"; billing from 2026-10-15 [checked] |
| S8 | https://aws.amazon.com/ivs/pricing/ | "$0.0720" per participant-hour; "20 participant hours per month" [checked] |
| S8b | https://ivs.rocks/real-time/ | under 300 ms (sweep paraphrase) |
| S9 | https://www.red5.net/webrtc-server/ | under 250 ms; 50 GB free (sweep paraphrase) |
| S10 | https://phenixrts.com/ | "< 1/2 second of latency"; SIS "Watch & Bet" [checked] |
| S11 | https://www.agora.io/en/pricing/ | 10,000 free min; 400–800 ms Premium from a 404'd docs-legacy snippet |
| S12 | https://www.nanocosmos.net/ultra-low-latency/ | under 1 s camera to viewer (sweep paraphrase) |
| S13 | https://optiview.dolby.com/docs/theolive/ | HESP suits 1–5 s (sweep paraphrase) |
| S14 | https://www.wowza.com/blog/hls-latency-sucks-but-heres-how-to-fix-it | LL-HLS 2–3 s (sweep paraphrase) |
| S15 | https://arxiv.org/pdf/2310.03256 | LL-DASH 5.11 s tuned / 7.27 s default (sweep) |
| S16 | https://doc.haivision.com/SRT/1.5.3/Haivision/srt | SRT default receive buffer 120 ms (sweep) |
| S17 | https://support.google.com/youtube/answer/7444635 | ULL "latency less than 5 seconds" [checked] |
| S18 | https://datavideo.com/global/faq/360058612633 | "delay of 2 to 5 seconds" (sweep) |
| S19 | https://yanaga.io/blog/youtube-ultra-low-latency-obs-mac | "between 3s to 4s" (sweep) |
| S20 | https://www.youtube.com/static?template=terms | "using any automated means (such as robots, botnets or scrapers)" (sweep) |
| S21 | https://stream-rise.com/blog/twitch-low-latency-video | "about 2-4 seconds" (sweep) |
| S21b | help.twitch.tv (did not load; search-result quote) | "1.5 seconds in certain cases" (sweep) |
| S22 | https://www.twitch.tv/challenger_series/schedule | search snippet only (sweep) |
| S23 | https://www.tt-series.com/wp-content/uploads/2026/07/TT-ELITE-SERIES-integrity-2.pdf | "technology partner – Sportradar" (sweep) |
| S24 | https://beter.co/setka-cup-opens-new-location-in-ukraine/ | "Only three people can be present in a room during the game" (sweep) |
| S25 | https://tabletennis.setkacup.com | "live 24/7" (sweep) |
| S26 | https://en.wikipedia.org/wiki/China_Smash_2026 ; https://www.globalgameguide.com/article/2026-wtt-china-smash-guide | "1–11 October"; US geo-block disputed (sweep) |
| S27 | https://developer.confluent.io/learn-more/podcasts/streaming-real-time-sporting-analytics-for-world-table-tennis/ | "within the milliseconds" (sweep; an interview goal) |
| S28 | https://www.sportsvideo.org/2025/02/10/super-bowl-lix-tubi-leads-all-streaming-platforms-in-least-lag-time-according-to-phenix-report/ ; https://sportsmintmedia.com/wtt-and-ittf-unlock-free-u-s-and-french-coverage-through-fanduel-tv-and-lequipe/ | OTT 26–78 s behind (sweep) |
| S29 | https://www.prnewswire.com/news-releases/polymarket-secures-exclusive-atp-tour-streaming-rights-for-prediction-markets-302841534.html ; https://x.com/Polymarket/status/2084371830635160010 ; S29c https://www.newspoly.net/blog/polymarket-kyc-verification | "Registered Polymarket users in the U.S. can watch live ATP matches" (sweep); KYC from a third-party guide |
| S30 | https://sportradar.com/betting-gaming/products/live-streams/ ; https://betradar.com/live-streaming/live-channel-trading/ | "eight seconds faster than any TV signal" (sweep) |
| S31 | https://www.openbet.com/news/sportradar-announces-close-of-acquisition-of-img-arena-and-its-strategic-portfolio-of-global-sports-betting-rights | IMG Arena deal closed 2025-11-03 (sweep) |
| S32 | https://sharpapi.io/compare/sportradar-alternative | "enterprise contracts starting at $10,000+/month" (third party; sweep) |
| S33 | https://docs.sportradar.com/live-data/latency-indicator-beta | "~0–<4 seconds" (sweep) |
| S34 | https://www.statsperform.com/products/official-wta-data-streaming/ | "32% of points more than 1 second faster"; video for "licensed sportsbooks" [checked] |
| S35 | https://regensports.substack.com/p/i-attended-sportradars-game-set-tech | "TDI's true real-time system compresses that gap" (sweep) |
| S36 | https://www.itia.tennis/media/3tihxdff/tennis-anti-corruption-program-2026.pdf | TACP D.1.p and B.38 (sweep) |
| S37 | https://www.itftennis.com/media/15546/2026-wtt-regulations.pdf | ITF WTT regulations XI.B; Covered Persons (sweep) |
| S38 | https://www.usopen.org/pdf/Stars-of-the-Open-Ticket-Terms-and-Conditions.pdf | search snippet only; the PDF fetch timed out (sweep) |
| S39 | https://wttwebcmsprod.blob.core.windows.net/imagedocuments/2025%2005%2020%20WTT%20EU%20Smash%20-%20Event%20Ticket%20Policy_v1%20clean%20.pdf_1748403514039 | sections 6.2, 6.3, 9.1 (sweep) |
| S40 | https://en.wikipedia.org/wiki/Courtsiding | "20 spectators were caught courtsiding" (sweep) |
| S41 | https://montecarlotennismasters.com/en/medias-en/charte-accreditation/ | (sweep) |
| S42 | https://docs.polymarket.com/api-reference/geoblock | "Primary Servers: eu-west-2"; US/UK close-only (sweep) |
| S43 | https://docs.polymarket.com/concepts/order-lifecycle | "waits for the market's configured delay window before matching" [checked]; no duration given |

Internal sources (I): `research/v2/latency/RESULTS.md`, `research/v2/tier0/RESULTS.md`, `research/v2/tier0_v3/RESULTS.md`,
`results/decay/decay.json`, `results/tier0/latency_sweep.{json,csv}` (uncommitted at time of writing),
`research/home_stream/probe_latency.py` (preliminary 25–30 s runs of HLS, LL-HLS, WebRTC/WHEP and YouTube on arena
"granite", 2026-10-03 20:30–20:40 UTC; output not committed).

**Gaps.** The sweeps hit the 200-search cap. The truncated tails of four sweeps were lost in the merge: Stats
Perform's route and the betting-video routes after it, WTT live scores onward, FanDuel onward, and venue-legal
routes 3 onward. Nothing after the cut points is represented here except where it was re-checked above.
