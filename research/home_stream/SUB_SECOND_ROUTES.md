# Sub-second video: every route to ≤ 1 s, and how to present it

Merged from five read-only web sweeps run on 2026-10-03: webrtc-platforms, betting-video, tt-leagues, public-ll and
venue-legal. A few key figures were re-fetched today to check them; those are marked **[checked]**. No accounts were
created, nothing was bought and no forms were submitted. Machine-readable copy: `results/home_stream/sub_second_routes.json`.

**Adversarial source check (second pass, 2026-10-03).** Every source cited for routes A1–A11 and B2 was re-opened
(legal PDFs were downloaded and their text extracted). Each is now marked **verified**, **corrected** or
**not re-verified**. Main changes: A2–A7 are vendor claims only and none is "free tonight" by any source; Agora's
latency figure is unsourced; the "14–50 ms to London" leg and the "110 ms" spectator figure had no source; the
anti-corruption code binds players, their staff and accredited people, not spectators; the "$10k+/month" figure is a competitor's guess about
*data* contracts; the third-party "KYC needs an SSN" guide says nothing of the kind about Polymarket; and our own
sub-second pipeline has **not yet been measured**, so every "[X] ms" in §4 stays out of the deliverables until it is.

Notation. **M** is a measured figure: **M-ind** when run by an independent journalist or blogger, **M-vendor** when
run and published by a company that sells the product or services around it. **C** is a vendor or platform claim
(marketing, no method published). **I** is internal to this repo. Glass-to-glass (g2g) runs from the moment light hits the camera to the
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

### Band A: routes to ≤ 1 s (measured, claimed or physically possible)

Only A1 has independent sub-second measurements (S1, S2); A1b rests on a vendor test (S4). Both are **our own
footage, not a Polymarket match**, and neither has been measured by us yet.
A2–A7 are sub-second **by vendor claim only** (C). A8–A11 are the routes to a real match; none is open to us tonight.

| # | route | what we get | latency (M-ind / M-vendor / C) | cost | legal / eligible for us | usable tonight? | path to obtain |
|---|---|---|---|---|---|---|---|
| A1 | **Self-hosted WebRTC on our own camera**: OBS ≥ 30 (WHIP) into MediaMTX or Broadcast Box; WHEP browser viewer. `engine/vision` cannot read WebRTC, so the CV process would read the same stream as RTSP from MediaMTX ("Streams are automatically converted from a protocol to another" [S44]) | our own footage only (a rally on our table, a tennis hit). **Not a Polymarket match** | **M-ind: 42 ms** local, OBS 30 beta to Broadcast Box; method not described [S1, verified]. **M-ind: about 0.4 s** through the public Broadcast Box server, read off a stopwatch [S2, verified]. M-vendor: 130 ms local, 170 ms remote over a 30 ms-RTT California–Oregon relay, 30 fps webcam [S4, verified]. M-vendor (consultancy field report): MediaMTX p50 180 ms LAN-only, 310 ms industrial LAN, 520 ms cross-region, 740 ms over 4G [S3, verified]. **We have not measured our own pipeline yet** | $0. MediaMTX is MIT-licensed [S44]; OBS is free; Broadcast Box licence not checked | **yes**: own footage | **possible tonight, not done yet**: nothing is installed or measured | install OBS + MediaMTX locally and measure (§4.4) |
| A1b | Camera straight into the CV process (`engine/vision/stream.py --source 0`), no streaming hop | same, minus the network leg | M-vendor: in a 132 ms webcam-to-monitor loop, "the camera itself and the USB bus (~100 ms)" dominate, 30 fps camera [S4, verified]. The 8.3 ms figure is only the frame interval at 120 fps (I: `results/decay/decay.json` camera_s), not a g2g measurement; whether we own a 120 fps camera: no public source; assumption. CV leg 84 ms p50 / 127 ms p90, measured on a **video file** with a stand-in classifier, calls disabled, and it does not keep up with 120 fps (I: decay.json `cv_measured_s`) | $0 | yes | **possible tonight, not done yet**: `stream.py` accepts a webcam index, but every in-repo vision run so far read a video file (I: `results/engine/vision_bench.json`) | run `--source 0` with `--corners` and log call timestamps |
| A2 | Cloudflare Stream WebRTC (WHIP/WHEP; "Stream Live WebRTC is going GA") | our own footage, relayed through a CDN | **C only**: "less than 500 milliseconds of latency" [S7, verified]. No independent measurement found | $1 per 1,000 min delivered; WebRTC billing "will begin on October 15th, 2026" [S7, verified]. Stream storage is "prepaid", sold in $5/month increments [S7b, verified]; whether a WebRTC live input needs a paid Stream subscription is not stated, so **"free tonight" is unsupported** (earlier "free tonight" was an inference) | yes; Cloudflare account, not a betting account | **only after the user signs up**, and possibly pays for Stream (unverified); own footage only | user creates the account; WHIP from OBS |
| A3 | Amazon IVS Real-Time | our own footage | **C only**: "can be under 300 milliseconds from host to viewer" (IVS showcase site, no method) [S8b, verified] | $0.0720 per participant-hour (North America/Europe); new AWS customers get "20 participant hours per month" for "the first 12 months" [S8, verified]. Whether AWS sign-up needs a payment card: not checked; assumption that it does | yes; AWS account | **only after the user signs up**; own footage only | user creates the account |
| A4 | Red5 Cloud | our own footage | **C only**: "sub-250 ms latency" [S9, verified] | C: "50 GB For Free Monthly"; "No credit card is required to sign up" [S9, verified] | yes; account | **only after the user signs up**; own footage only | user creates the account |
| A5 | Phenix. Phenix's home page quotes betting-video suppliers SIS ("Watch & Bet") and RMG ("in play betting") as customers | our own footage | **C only**: "< 1/2 second of latency" [S10, verified] | "FREE TRIAL" link goes to a marketing sign-up form; terms not shown [S10, verified] | yes for our own content | **unlikely tonight**: the trial is a request form with unknown turnaround (assumption) | user requests the trial |
| A6 | Agora Interactive Live Streaming, Premium tier | our own footage | **no verified figure.** The earlier "400–800 ms Premium, 1.5–2 s Standard" came from a search snippet of a docs page that now returns 404; the current product overview says only "ultra-low latency" [S11b, checked]. Downgraded | "First 10,000 combined RTC minutes free every month", then $0.59 per 1,000 min [S11, verified] | yes; account | **only after the user signs up**; own footage only; latency unknown | user creates the account |
| A7 | nanocosmos nanoStream (H5Live / MoQ) | our own footage. The vendor markets to "iGaming & Live Casinos" | **C only**: "delivers video from camera to viewer in under one second" [S12, verified] | C: "Start for Free"; no prices on the page [S12, verified] | yes; account | **only after the user signs up**; own footage only | user creates the account |
| A8 | **Organiser-consented camera or raw contribution feed at a private table-tennis league** (TT Elite Series, Czech Liga Pro, TT Cup) | a real Polymarket-listed match | **nobody has measured this route.** Inference only: A1-type physics plus a venue-to-server network leg (no public source; assumption) gives roughly 0.15–0.5 s g2g. An SRT contribution link adds its receive latency, "125 ms" by default on Haivision sources [S16, verified; corrected from 120 ms] | no public source (price unknown) | **legal only with written consent** from the rights holder. TT Elite Series names "technology partner – Sportradar", but in its *integrity* policy (anti-match-fixing, Sportradar's Fraud Detection System), not as a stated video or data deal [S23, verified; exclusivity is an assumption]. The same policy bars anyone associated with the tournament from helping "third parties to engage in such betting" [S23], so consent for a **trading** purpose looks unlikely; consent for non-trading research is untested. Czech Liga Pro and TT Cup rights holders: not identified; no public source. Setka Cup is ruled out: "Only three people can be present in a room during the game: two players and one referee" (BETER, 2021) [S24, verified] | **no**: no consent has been requested; turnaround unknown | email the organiser for research (non-trading) access to their raw feed or a camera position. This is the **only legal ≤ 1 s route to a real Polymarket match** we found, and it is hypothetical |
| A9 | B2B betting video sold to licensed sportsbooks: Sportradar/Betradar streams (reportedly now including the ex-IMG Arena portfolio [S31, not re-verified]), Stats Perform, BETER (Setka Cup) | real ATP, Challenger, WTA, Grand Slam and table-tennis video | **no absolute g2g published.** C: "up to eight seconds faster than any TV signal", relative to TV [S30, verified; earlier quote dropped "up to"]. Stats Perform's WTA page gives no video latency, only "low latency" for its shot-by-shot *data* feed [S34, verified]. A "sub-second video" claim reported by the betting-video sweep lost its URL: **unverified, do not cite** | **no public price.** The "$10,000+/month" figure is a competitor's (SharpAPI) sales-page estimate for Sportradar *data* contracts, not video [S32, verified; recharacterised] | **not eligible**: Stats Perform sells "Premium Live WTA video streams to licensed sportsbooks" [S34, verified]; Sportradar sells to operators, betting shops and trading desks [S30]. No research licence published | **no** | operator contract only |
| A10 | Spectator's own camera at an ATP, Challenger, WTA, ITF or WTT event | a real match | physically about 130–170 ms (S4's webcam-to-monitor test, not a venue) [corrected from 110–170 ms, which no source gave] | ticket | **no.** Spectators are bound by event and ticket rules; the anti-corruption code's courtsiding offence (TACP D.1.p) binds only Covered Persons, i.e. players, their staff and tournament or accredited personnel [S36, verified; earlier text overstated it]. ITF World Tennis Tour regulations XI.B require tournaments to ban devices in spectator areas used to collect Tournament Data "for Betting or any other commercial purposes" [S37, verified; applies to ITF events]. The 2026 Stars of the Open (a US Open exhibition) ticket terms ban capture for "betting, gambling or prediction markets activity" [S38, verified]. WTT Europe Smash 2025 ticket terms ban recording devices (6.2), streaming match play (6.3) and court-siding (9.1) [S39, verified]. ATP and WTA tour-level ticket terms: not fetched; assumed similar. At the 2016 US Open, "20 spectators were caught courtsiding" [S40, verified]. Fails the hackathon ToS rule | **no** | none (excluded) |
| A11 | Student media accreditation | press access, no feed rights | n/a | n/a | **no.** The Monte-Carlo media charter bans "any form of gambling or betting activity whatsoever" [S41, verified]. Under the TACP, anyone accredited at an Event at the request of tournament staff is Tournament Support Personnel, hence a Covered Person bound by D.1.p [S36, verified; earlier text cited S37] | **no** | none (excluded) |

**Independent check on A2–A7.** The only independent multi-vendor glass-to-glass test we found (Streaming Media,
Oct 2023, vendors anonymised, wall-clock timestamps read by hand) measured **no** managed service under 0.58 s on a
normal network, and every one at 1.78–2.34 s on 4G [S5, verified]. The sub-500 ms vendor claims above are therefore
uncorroborated, and none of A2–A7 carries a Polymarket match anyway.

### Band B: best routes at 1–3 s

| # | route | what we get | latency (M / C) | cost | legal / eligible for us | usable tonight? | path to obtain |
|---|---|---|---|---|---|---|---|
| B1 | Managed WebRTC, WebSocket and HESP CDNs under real network conditions (Streaming Media test, Oct 2023, vendors anonymised) | our own footage | **M-ind** on a normal network: WebRTC 0.58 s and 1.07 s (two vendors), WebSockets 0.97 s and 1.17 s, HESP 1.12 s. On 5G: 0.69–1.63 s. **On 4G: 1.78–2.34 s** [S5, verified]. Burnt-in wall clock; timestamps read by hand | varies | yes | own footage only, after the user signs up | the cell uplink, not the protocol, decides whether we stay under 1 s |
| B2 | **Polymarket in-app ATP and Challenger streams** (supplied by TDI) | real ATP/Challenger video; no WTA, ITF or table tennis | **no public source** | assumption: free to registered users | US only. The release (2026-08-03) says "Registered Polymarket users in the U.S." can watch [S29, verified]; it does not say whether the account must be verified or funded. The earlier "KYC needs a US address, ID and SSN" claim is **withdrawn**: the cited third-party guide [S29c, re-checked] mentions an SSN only for Kalshi and says Polymarket needs no ID, so it supports neither reading. Polymarket US account requirements: no public source checked. Screen capture into CV: no public source. Creating an exchange account is outside what we may do | **unknown, treat as no**: only if a team member already holds a Polymarket US account and its terms allow capture; neither is verified | read the Polymarket US terms first; then measure latency against the book |
| B3 | Twitch Low Latency (for example the "Challenger_Series" channel; not confirmed to be the Polymarket-listed TT Challenger) | free public video | C: "about 2-4 seconds" (third party) [S21]; Twitch "down to 3 seconds", "1.5 seconds in certain cases" in Korea (search-result quote; page did not load) [S21b]. Encoder to player, not g2g | free | viewing yes; CV on captured frames is a ToS risk | only if the channel is live (snippet: next stream Thursday 06:30 UTC) [S22] | the player shows "Latency to Broadcaster" in Advanced video stats |
| B4 | YouTube Ultra-low latency: Setka Cup Live, TT Elite Series, WTT (China Smash, 1–11 Oct) | free public video of Polymarket-listed table tennis | C: Ultra-low "latency less than 5 seconds", Low "less than 10 seconds" [S17, checked]; 2–5 s (third-party FAQ) [S18]; M: 3–4 s by ear on one blogger's own stream [S19]. Whether these channels use ULL: unknown | free | viewing allowed for "personal, non-commercial use"; ToS bans access "using any automated means" [S20]. WTT may be geo-blocked in the US; do not use a VPN [S26] | **yes** (Setka is live 24/7 [S25]) | watch only; no automated capture |
| B5 | Fast scout data, not video: Stats Perform RunningBall, Sportradar/TDI umpire-chair data | point events | C: RunningBall is "32% of points more than 1 second faster" than the umpire feed (claim, no method) [S34, verified]; Sportradar's "Low" band is "~0–<4 seconds" [S33] | no public price | operators only | no | operator contract |

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
[S5, verified again in the second pass; Oct 2023, timestamps "manually reviewed and typed into a spreadsheet"]. Managed WebRTC is therefore **not** reliably under 1 s over the public internet. Only the local and
LAN figures (A1) are.

---

## 2. Bottom line

**Is ≤ 1 s achievable tonight from home on a Polymarket-listed match? No.**

1. **Measured, not just inferred.** Setka Cup's own Flussonic server has a public WebRTC (WHEP) output, which its embed
   player uses. It is the only public WebRTC feed of a Polymarket-listed match we found. Our
   preliminary probe puts that WebRTC feed a median **12.2 s** behind the burned-in arena clock. LL-HLS was 13.0 s,
   HLS 19.4 s and YouTube 20.2 s (C1; the YouTube run used yt-dlp, see §4.5). The transport is not the bottleneck:
   about 12 s is added before the CDN, unless the arena clock itself is offset (C1). Other public streams claim
   YouTube ULL at under 5 s (C) or Twitch LL at 2–4 s (C), which is still far above 1 s.
2. Every sub-second route to real match video falls into one of two kinds:
   - a B2B betting feed sold only to licensed sportsbooks (A9), whose absolute latency is unpublished anyway;
   - a camera in the venue. At ATP, WTA, ITF and WTT events, spectators' recording or data capture for betting is
     barred by ITF regulations and ticket terms (A10; the anti-corruption code covers players and accredited staff,
     A11). At a private table-tennis league it needs written consent we do not have, and TT Elite Series' integrity
     policy makes consent for a trading purpose unlikely (A8).
3. The one rights-holder stream tied to a prediction market, Polymarket's in-app ATP stream (B2), is for "registered"
   US users of an exchange; whether it needs a verified or funded account, whether capture is allowed, and its
   latency are all unpublished.

**Is ≤ 1 s achievable tonight from home on our own footage? Possible for $0, but not done yet.** Others have measured
self-hosted WebRTC at 42 ms locally (webrtcHacks, method not described) and about 0.4 s through a public relay
(Gigazine, stopwatch); vendor and consultancy reports give 130–740 ms (A1). **We have no sub-second number of our
own until we run §4.4.** Hosted services (A2–A7) claim under 0.5–1 s, but only by vendor claim, and each needs an
account the user would have to create.

**Cheapest legal path to ≤ 1 s:**
- *For the demo or video:* A1, $0, on our own camera, once measured.
- *For a real Polymarket match:* A8, written consent from a private table-tennis rights holder (TT Elite Series,
  Czech Liga Pro or TT Cup) for their raw contribution feed or a camera position, for non-trading research. The
  price is unknown (no public source) and it is not available tonight. The only alternative is a sportsbook B2B
  licence (A9), which we are not eligible for; no public price exists (the often-quoted "$10k+/month" is a
  competitor's guess about data, not video).

**Even ≤ 1 s does not win the race.** In our backtest the break-even video delay is **1.09 s in sample and 1.01 s
out of sample** under the headline timing reading. Under the calibrated reading it is **0.34 s / 0.30 s**. A 1 s
feed sits at break-even, and only the courtside camera (V ≈ 0, not available to us) is clearly positive in sample;
out of sample even V = 0 has a per-share CI that includes zero. Details in §4.2.

Also note that the international Polymarket docs list the US and UK as close-only ("Close-Only on Frontend and
API") and the primary servers as eu-west-2 [S42, verified]. This changes nothing here, since we place no orders. It
does mean any live-trading claim would be false twice over.

---

## 3. Latency budget for the best route

Best route to a real match: an organiser-consented 120 fps camera at the venue, WebRTC to a London box running our
CV, and a London gateway to Polymarket (eu-west-2 [S42]). This is A8: hypothetical, not available tonight, and no
leg below has been measured on this route; the per-leg figures come from other setups.

| leg | value | type | source |
|---|---|---|---|
| bounce → frame captured | 0–8.3 ms frame interval at 120 fps (assumed camera); about 100 ms camera + USB for a 30 fps webcam | assumption / M-vendor | I `results/decay/decay.json` (camera_s); S4 |
| encode | about 10 ms | M-vendor | S4 |
| venue → London network | Europe 10 ms … Asia 100 ms (model assumption). **No public source** for a venue-to-London figure; the earlier "14–50 ms one way [S4]" is withdrawn (S4 measured only a 30 ms RTT California–Oregon) | assumption | I tier-0 §8 item 9 |
| jitter buffer + decode | about 10 ms decode; **g2g total 130–170 ms (one vendor test), p50 180 ms LAN-only, 520 ms cross-region (consultancy report)** | M-vendor | S4, S3 |
| **video subtotal (g2g)** | **about 0.13–0.52 s** (other people's setups; not measured on this route) | M-vendor / inference | |
| CV inference | 20 ms assumed in the tier-0 model; **84 ms p50 / 127 ms p90 measured** on a laptop M4 from a video file (stand-in classifier, calls disabled, frames skipped to bound lag); out-calls can come 25–100 ms *before* the event | assumption / M (I) | I `results/decay/decay.json` cv_measured_s; `research/v2/tier0_v3/RESULTS.md` |
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

**Rule for `[X]`.** `[X]` is a placeholder for our own measured g2g latency (§4.4). **It has not been measured.**
If it is still unmeasured when the paper, deck or video is produced, use the "not measured" variant of each text
below and delete every sentence containing `[X]`. Never fill it with an estimate or with someone else's figure
(42 ms, 0.4 s, 180 ms are other people's setups).

**Can say:**
- We simulated a 1 s and a 0.5 s video feed as an **assumed-data scenario**. We did not have such a feed.
- Sub-second video of these matches exists only as licensed sportsbook feeds, or as a camera at the venue with the
  organiser's consent. We have neither.
- The fastest public feed of a Polymarket-listed match we found, Setka Cup's own WebRTC stream, measured a median
  12.2 s behind the on-screen arena clock in a preliminary test (C1). Say "preliminary" until the full run lands.
- *Only after §4.4 is done:* we measured our own camera → WebRTC → screen at **[X] ms g2g** on our own footage
  (not a match), and say whether the figure is LAN or remote. Say "camera → WebRTC → CV" only if the CV process
  itself read that stream and we timed its calls; otherwise report the CV leg separately and say it was measured on
  a video file.

**Cannot say:**
- that we received live video of any Polymarket match at ≤ 1 s, or at any latency, into CV;
- "sub-second", "≤ 1 s" or "1-second" about anything we **have**, except our own measured own-footage pipeline;
  "a 1 s feed" may appear only as a hypothetical in the simulation;
- "real-time match feed", "sub-second match stream", "we traded" or "live P&L";
- "WebRTC is sub-second" without the qualifier (one independent test of two managed services: 0.58 s and 1.07 s on
  a normal network; 2.2–2.3 s on 4G);
- any vendor claim from §1 (A2–A7, A9) as if it were a measurement;
- that a 1 s feed is profitable. It is at break-even;
- that a courtside camera is an option for us. V = 0 is a reference point, not a route.

### 4.2 Numbers to cite (tier-0 sweep, own 120 fps CV, headline per-tournament timing reading, 20 seeds)

Source: `results/tier0/latency_sweep.json` and `.csv`. The model is `scripts/tier0_latency_sweep.py`. These files
were regenerated at 2026-10-03 16:39 EDT and are committed in `f5ff9ff` together with
`research/v2/tier0/LATENCY_SWEEP.md` (the figures below were re-read from the committed JSON in the second pass).
The V = 0 row reproduces the published tier-0 headline exactly. The OOS period is burned, not blind.

| video delay V | IS c/share [95 % CI] | IS $/day ± SD | burned OOS c/share [CI] | OOS $/day ± SD |
|---|---|---|---|---|
| 0 (courtside camera, not available to us) | +1.10 [0.82, 1.38] | $88.8 ± 21.3 | +0.58 [−0.08, 1.21] (CI includes 0) | $46.4 ± 39.0 |
| **0.5 s** | **+0.61 [0.08, 1.14]** | **$28.4 ± 19.0** | −0.02 [−1.22, 1.09] | $15.2 ± 36.0 |
| **1.0 s** | **+0.40 [−0.32, 1.08]** | **$14.8 ± 14.7** | −0.38 [−2.08, 1.20] | $4.3 ± 29.6 |

- **Break-even V:** 1.09 s IS and 1.01 s OOS (seed-mean curve). The per-share CI stays above 0 only for V < 0.65 s
  (IS). OOS never excludes 0, not even at V = 0.
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
> by a hypothetical video latency V. The model uses real Polymarket tapes, fees and 1 s venue delays, with timing
> and fills parameterised from our own measurements. We report V = 1.0 s and V = 0.5 s. For scale, in one
> independent glass-to-glass test two managed WebRTC services measured 0.58 s and 1.07 s on a normal network and
> 2.2–2.3 s on 4G (Streaming Media, Oct 2023). For these matches, feeds this fast are sold only to licensed
> sportsbooks (Sportradar, Stats Perform, BETER), or would need a camera at the venue with the organiser's written
> consent. We have neither. The fastest public feed of a Polymarket-listed match we found, Setka Cup's own WebRTC
> stream, ran a median 12.2 s behind the on-screen arena clock in a preliminary test.
>
> *Last sentence, if §4.4 was done:* On our own footage only (not a match), our camera → WebRTC → screen pipeline
> measured [X] ms g2g (p50, LAN|remote).
> *Last sentence, if not:* We did not measure a sub-second pipeline of our own.

**Paper, results paragraph:**

> With a hypothetical 1.0 s video feed the strategy is at break-even: +0.40¢/share [−0.32, 1.08] and $15 ± 15/day
> in sample, −0.38¢ [−2.08, 1.20] and $4 ± 30/day on the burned out-of-sample period. With a 0.5 s feed it earns
> +0.61¢ [0.08, 1.14] and $28 ± 19/day in sample, but is not distinguishable from zero out of sample (−0.02¢
> [−1.22, 1.09]). The break-even video delay is 1.09 s (IS) and 1.01 s (OOS) under our headline timing reading. If
> the book reprices 0.68 s after the bounce, the strategy loses at every delay, a courtside camera included. Under
> our calibrated inference (1.35 s) the feed must be under about 0.3 s. Because the venue's 1 s order delay comes
> on top of the feed, video speed is necessary but not sufficient.

**Deck slide** (title, then bullets, then footnote):

> **If we had a 1-second match feed: a simulation (assumed data)**
> - Courtside camera (V = 0, not available to us): +$89/day in sample; +$46/day out of sample, CI includes 0
> - 0.5 s feed: +$28/day in sample (CI just above 0); not significant out of sample
> - 1.0 s feed: break-even (+$15/day IS, +$4/day OOS, both CIs include 0)
> - We have no sub-second match feed: it is sold only to licensed sportsbooks. The best public feed we found ran
>   about 12 s behind (preliminary)
> - *Only if measured:* Our own camera → WebRTC → screen, own footage, not a match: [X] ms
>
> *Footnote: Counterfactual with assumed data: licensed feed/video not purchased; parameters measured.
> results/tier0/latency_sweep.csv. WebRTC g2g: Streaming Media, Oct 2023.*

**Video narration** (about 20 s). Use variant B unless §4.4 has produced [X].

> *A (measured):* "From home, we can't legally get live video of these matches in under a second. The fastest
> public feed we found ran about twelve seconds behind the arena clock in a preliminary test. Feeds under a second
> go only to licensed sportsbooks, or come from a camera at the venue. On our own footage, not a match, our camera
> reached the screen over WebRTC in [X] milliseconds. Then we asked the backtest what a one-second match feed would
> be worth. The answer is break-even. At half a second it's positive in sample but not out of sample. This is a
> simulation with assumed data, not a live result."
>
> *B (not measured):* "From home, we can't legally get live video of these matches in under a second. The fastest
> public feed we found ran about twelve seconds behind the arena clock in a preliminary test. Feeds under a second
> go only to licensed sportsbooks, or come from a camera at the venue. So we asked the backtest what a one-second
> feed would be worth if we had one. The answer is break-even. At half a second it's positive in sample but not out
> of sample. This is a simulation with assumed data, not a live result."

**On-screen caption:**
- measured: `ASSUMED-DATA SCENARIO · no sub-second match feed · 1 s / 0.5 s video simulated · own-footage WebRTC: [X] ms`
- not measured: `ASSUMED-DATA SCENARIO · no sub-second match feed · 1 s / 0.5 s video simulated, not received`

### 4.4 Measuring our own [X] tonight (A1, $0)

1. Put a millisecond counter on a high-refresh screen in the camera's view.
2. Stream it: OBS ≥ 30 (WHIP output) into a local MediaMTX (or Broadcast Box), then view it in a browser over WHEP.
   A hosted remote-path figure (A2–A4) needs the user to create an account first; Cloudflare's "free until
   2026-10-15" is **not** established, since Stream may need a paid subscription (not stated in S7/S7b).
3. Film the source counter and the viewer screen together with a 240 fps phone, and read about 200 frame pairs
   [S3 method]. An alternative is to reuse the burned-in-clock method of `probe_latency.py`, with an NTP-synced
   clock overlay.
4. Report p50 and p95, and say whether the figure is LAN or remote. This is camera → WebRTC → **screen**.
5. For a camera → call number, point `python -m engine.vision.stream --source <MediaMTX RTSP URL>` at the same
   stream (MediaMTX converts WHIP input to RTSP [S44]) and time its calls; or quote the CV leg separately as
   "84 ms p50, measured on a video file with a stand-in classifier" (I: decay.json). Do not add the two and call the
   sum measured.


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

[checked] means re-fetched on 2026-10-03 for the merge. **[verified]** means re-opened again in the second-pass
adversarial check on 2026-10-03 and the quote or figure found as stated (or as corrected here). **[not re-verified]**
means the second pass could not open it (HTTP 403/429, timeout) or did not try; treat it as the sweep's report only.
Type of source: ind = independent, vendor = sells the product or services around it, competitor = sells a rival
product, official = rights holder, regulator or the platform itself.

| id | URL | short quote or note |
|---|---|---|
| S1 | https://webrtchacks.com/webrtc-cracks-the-whip-on-obs/ | ind (webrtcHacks, Chad Hart, 2023-08-22): "my glass-to-glass latency was only 42 ms" (OBS 30 Beta 2, local Broadcast Box; method not described) [verified] |
| S2 | https://gigazine.net/gsc_news/en/20260117-broadcast-box-webrtc/ | ind (Gigazine, 2026-01-17): stopwatch "lag between the streamer and the viewer is about 0.4 seconds" via public server [verified] |
| S3 | https://www.adaptnxt.com/blogs/mediamtx-whip-whep-latency-benchmarks-4-deployments | vendor (AdaptNXT consultancy, 2026-04-24, client field reports): p50/p95 180/240 ms LAN-only; 310/480 industrial LAN; 520/890 cross-region; 740/1,180 4G; method "240 fps phone camera" [verified] |
| S4 | https://transitiverobotics.com/blog/webrtc-latency-breakdown/ | vendor (Transitive Robotics measuring its own product, 2026-05-06): local 130 ms, remote 170 ms (30 ms RTT, California–Oregon); "the camera itself and the USB bus (~100 ms)"; 30 fps camera. **No London or 14–50 ms figure** [verified; earlier citation for a London leg withdrawn] |
| S5 | https://www.streamingmedia.com/Producer/Articles/Editorial/Featured-Articles/Glass-to-Glass-Report-Comparing-Low-Latency-Streaming-Providers-161238.aspx | per-network table, Oct 2023; method: "a burnt-in wall clock in the top right corner" [checked] |
| S6 | https://www.rfc-editor.org/rfc/rfc9725.html | official: "WebRTC-HTTP Ingestion Protocol (WHIP)", Standards Track, March 2025 [verified] |
| S7 | https://developers.cloudflare.com/stream/webrtc-beta/ | vendor: "less than 500 milliseconds of latency" (claim); "Stream Live WebRTC is going GA"; WebRTC delivery billing "will begin on October 15th, 2026" [verified] |
| S7b | https://developers.cloudflare.com/stream/pricing/ | vendor: storage "is a prepaid pricing dimension", $5/month per 1,000 min; $1 per 1,000 min delivered; no free tier stated [verified, second pass] |
| S8 | https://aws.amazon.com/ivs/pricing/ | vendor: "$0.0720" per participant-hour (NA/EU); "20 participant hours per month" for "the first 12 months" (new customers) [verified] |
| S8b | https://ivs.rocks/real-time/ | vendor showcase: "latency that can be under 300 milliseconds from host to viewer" (claim, no method) [verified] |
| S9 | https://www.red5.net/webrtc-server/ | vendor: "sub-250 ms latency" (claim); "50 GB For Free Monthly"; "No credit card is required to sign up" [verified] |
| S10 | https://phenixrts.com/ | vendor: "< 1/2 second of latency" (claim); SIS quote "true Watch & Bet experiences"; RMG "in play betting"; FREE TRIAL is a marketing form [verified] |
| S11 | https://www.agora.io/en/pricing/ | vendor: "First 10,000 combined RTC minutes free every month"; $0.59 per 1,000 min. **No latency figure on this page** [verified] |
| S11b | https://docs.agora.io/en/interactive-live-streaming/overview/product-overview | vendor: only "ultra-low latency"; no Premium/Standard ms figures [checked, second pass] |
| S12 | https://www.nanocosmos.net/ultra-low-latency/ | vendor: "delivers video from camera to viewer in under one second" (claim); "Start for Free" [verified] |
| S13 | https://optiview.dolby.com/docs/theolive/ | HESP suits 1–5 s (sweep paraphrase) |
| S14 | https://www.wowza.com/blog/hls-latency-sucks-but-heres-how-to-fix-it | LL-HLS 2–3 s (sweep paraphrase) |
| S15 | https://arxiv.org/pdf/2310.03256 | LL-DASH 5.11 s tuned / 7.27 s default (sweep) |
| S16 | https://doc.haivision.com/SRT/1.5.3/Haivision/srt | vendor docs: "The default latency value on the source is 125 ms." [verified; earlier "120 ms" corrected] |
| S17 | https://support.google.com/youtube/answer/7444635 | ULL "latency less than 5 seconds" [checked] |
| S18 | https://datavideo.com/global/faq/360058612633 | "delay of 2 to 5 seconds" (sweep) |
| S19 | https://yanaga.io/blog/youtube-ultra-low-latency-obs-mac | "between 3s to 4s" (sweep) |
| S20 | https://www.youtube.com/static?template=terms | "using any automated means (such as robots, botnets or scrapers)" (sweep) |
| S21 | https://stream-rise.com/blog/twitch-low-latency-video | "about 2-4 seconds" (sweep) |
| S21b | help.twitch.tv (did not load; search-result quote) | "1.5 seconds in certain cases" (sweep) |
| S22 | https://www.twitch.tv/challenger_series/schedule | search snippet only (sweep) |
| S23 | https://www.tt-series.com/wp-content/uploads/2026/07/TT-ELITE-SERIES-integrity-2.pdf | official (TT Elite Series integrity policy): "technology partner – Sportradar" in an anti-match-fixing context; 3(b) bars enabling "third parties to engage in such betting" [verified, PDF text extracted] |
| S24 | https://beter.co/setka-cup-opens-new-location-in-ukraine/ | official (BETER, 2021-02-09): "Only three people can be present in a room during the game" [verified] |
| S25 | https://tabletennis.setkacup.com | "live 24/7" (sweep) |
| S26 | https://en.wikipedia.org/wiki/China_Smash_2026 ; https://www.globalgameguide.com/article/2026-wtt-china-smash-guide | "1–11 October"; US geo-block disputed (sweep) |
| S27 | https://developer.confluent.io/learn-more/podcasts/streaming-real-time-sporting-analytics-for-world-table-tennis/ | "within the milliseconds" (sweep; an interview goal) |
| S28 | https://www.sportsvideo.org/2025/02/10/super-bowl-lix-tubi-leads-all-streaming-platforms-in-least-lag-time-according-to-phenix-report/ ; https://sportsmintmedia.com/wtt-and-ittf-unlock-free-u-s-and-french-coverage-through-fanduel-tv-and-lequipe/ | OTT 26–78 s behind (sweep) |
| S29 | https://www.prnewswire.com/news-releases/polymarket-secures-exclusive-atp-tour-streaming-rights-for-prediction-markets-302841534.html ; https://x.com/Polymarket/status/2084371830635160010 ; S29c https://www.newspoly.net/blog/polymarket-kyc-verification | official release (2026-08-03): "Registered Polymarket users in the U.S." can watch; ATP Tour and Challenger; TDI; no latency or account-tier detail [verified]. S29c (third party, 2026-03-30) mentions an SSN only for **Kalshi** and says Polymarket needs no ID: it does **not** support the earlier "US address, ID and SSN" claim [re-checked; claim withdrawn]. X post [not re-verified] |
| S30 | https://sportradar.com/betting-gaming/products/live-streams/ ; https://betradar.com/live-streaming/live-channel-trading/ | vendor: "up to eight seconds faster than any TV signal" (claim, relative to TV); sold to operators, retail and trading desks [verified; "up to" restored] |
| S31 | https://www.openbet.com/news/sportradar-announces-close-of-acquisition-of-img-arena-and-its-strategic-portfolio-of-global-sports-betting-rights | IMG Arena deal closed 2025-11-03 (sweep) [not re-verified: HTTP 403/429] |
| S32 | https://sharpapi.io/compare/sportradar-alternative | competitor (SharpAPI sales page): "Sportradar pricing starts at $10,000+/month with enterprise contracts", about **data** feeds, not video [verified; recharacterised] |
| S33 | https://docs.sportradar.com/live-data/latency-indicator-beta | vendor docs: Low band "~0–<4 seconds" for live **data** updates [verified] |
| S34 | https://www.statsperform.com/products/official-wta-data-streaming/ | vendor: "32% of points more than 1 second faster" (claim, no method); "Premium Live WTA video streams to licensed sportsbooks"; no video latency figure [verified] |
| S35 | https://regensports.substack.com/p/i-attended-sportradars-game-set-tech | "TDI's true real-time system compresses that gap" (sweep) |
| S36 | https://www.itia.tennis/media/3tihxdff/tennis-anti-corruption-program-2026.pdf | official (TACP 2026): D.1.p "No Covered Person shall, while on site at an Event, make transmissions of…" (courtsiding); B.9 Covered Person = Player, Related Person or Tournament Support Personnel; B.37 includes accredited persons; B.38 "Wager" includes "any other form of financial speculation". Binds Covered Persons, not ticket-holding spectators [verified, PDF text extracted] |
| S37 | https://www.itftennis.com/media/15546/2026-wtt-regulations.pdf | official (ITF Men's and Women's World Tennis Tour Regulations 2026, ITF events only): XI.B tournaments must prohibit spectator-area devices used for Tournament Data "for Betting or any other commercial purposes" [verified, PDF text extracted] |
| S38 | https://www.usopen.org/pdf/Stars-of-the-Open-Ticket-Terms-and-Conditions.pdf | official (2026 Stars of the Open ticket terms, a US Open exhibition, not the main draw): "including, without limitation, betting, gambling or prediction markets activity" [verified, PDF downloaded] |
| S39 | https://wttwebcmsprod.blob.core.windows.net/imagedocuments/2025%2005%2020%20WTT%20EU%20Smash%20-%20Event%20Ticket%20Policy_v1%20clean%20.pdf_1748403514039 | official (WTT Europe Smash 2025 ticket T&Cs): 6.2 "Video and audio recording devices … are prohibited"; 6.3 streaming match play prohibited; 9.1 "Court-siding" [verified, PDF text extracted; other WTT events assumed similar] |
| S40 | https://en.wikipedia.org/wiki/Courtsiding | "20 spectators were caught courtsiding" (2016 US Open, 20-year bans) [verified] |
| S41 | https://montecarlotennismasters.com/en/medias-en/charte-accreditation/ | official (media accreditation charter): "any form of gambling or betting activity whatsoever" [verified] |
| S42 | https://docs.polymarket.com/api-reference/geoblock | official: "eu-west-2"; US and UK "Close-Only on Frontend and API" [verified] |
| S43 | https://docs.polymarket.com/concepts/order-lifecycle | "waits for the market's configured delay window before matching" [checked]; no duration given |
| S44 | https://github.com/bluenviron/mediamtx | open source: "Streams are automatically converted from a protocol to another"; MIT licence [verified, second pass] |

Internal sources (I): `research/v2/latency/RESULTS.md`, `research/v2/tier0/RESULTS.md`, `research/v2/tier0_v3/RESULTS.md`,
`results/decay/decay.json`, `results/engine/vision_bench.json` (CV benchmark, video-file input),
`results/tier0/latency_sweep.{json,csv}` and `research/v2/tier0/LATENCY_SWEEP.md` (committed in `f5ff9ff`),
`research/home_stream/probe_latency.py` (preliminary 25–30 s runs of HLS, LL-HLS, WebRTC/WHEP and YouTube on arena
"granite", 2026-10-03 20:30–20:40 UTC; output not committed).

**Gaps.** The sweeps hit the 200-search cap. The truncated tails of four sweeps were lost in the merge: Stats
Perform's route and the betting-video routes after it, WTT live scores onward, FanDuel onward, and venue-legal
routes 3 onward. Nothing after the cut points is represented here except where it was re-checked above.

**Second-pass gaps.** The web-search budget was exhausted, so the second pass could only re-open cited URLs, not look
for replacements. Not re-verified: S31 (403/429), the S29 X post, and Band B/C sources outside the top routes
(S13–S15, S17–S22, S25–S28, S35). Agora's latency (A6) and the Stats Perform "sub-second video" claim (A9) have no
working source. ATP and WTA tour-level ticket terms were not fetched; A10 relies on ITF, WTT and a US Open exhibition.
Setka Cup's terms on automated access are still unchecked.
