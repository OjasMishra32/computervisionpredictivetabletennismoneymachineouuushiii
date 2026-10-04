# Handoff: Yoan — ElevenLabs sponsor prizes ("COURTSIDE Voice")

**Owner:** Yoan Exposito · **Load: light** · **Deadline:** branch pushed by **9:00 AM EDT Sun Oct 4** (Devpost closes 11:00 AM EDT)
**Prizes targeted (opt in on Devpost when submitting):**
1. **MLH: Best Use of ElevenLabs** (wireless earbuds) — "Deploy natural, human-sounding audio with ElevenLabs ... give your project a voice."
2. **ElevenLabs: Best Project Built with ElevenLabs** (earbuds + 3 months ElevenLabs Scale per member).

Give this whole file to your AI coding agent as its brief. It is self-contained.

---

## 0. What COURTSIDE is (read this first, 2 minutes)

COURTSIDE is our Gator Quant Hacks 2026 Systematic Trading submission (team: Ojasva Mishra, Yoan Exposito, Rafael Penhas,
Ian Hoang). Thesis: in-play tennis prices on Polymarket are set by whoever learns the point first. Our computer vision
(CV) model watches the ball and calls the point (a MISS = the ball will land out / in the net; a BOUNCE = it lands in)
**before the ball lands**, so a trader could buy the stale price before the market reprices (~1 s after the point).
Everything is **paper trading only** (event rule: no funded accounts). Our paper, video and deck are being finalised by
Ojasva; **you do not touch them**.

Repo: https://github.com/OjasMishra32/computervisionpredictivetabletennismoneymachineouuushiii

Already built (you only READ these):
- `engine/vision/` — the streaming CV engine. It emits `CallEvent` objects (`engine/vision/events.py`):
  `call` ("MISS"/"BOUNCE"), `frame`, `t_frame`, `t_emit`, `p_miss` (0..1), `lead_ms` (how many ms before contact it called).
- `results/engine/online_events_L4.jsonl` — **172 real calls** the engine made on 7 held-out table-tennis games
  (one JSON per line: `call, frame, t_frame, t_emit, p_miss, lead_ms, source, media_t, ...`).
- `results/engine/demo_run.json` + `results/engine/engine_live_demo.mp4` — the engine demo: calls on a real clip, mapped to
  paper orders/fills on a recorded tennis book (illustrative, labelled).
- `results/e2e/trace.jsonl` + `results/e2e/summary.json` — the timed pipeline proof (frame -> order-ready in 54 ms).
- `docs/live/status.json` (written by `scripts/status_daemon.py`) — Mission Control status (headline numbers, jobs).
- `scripts/tts_elevenlabs.py` — **our existing ElevenLabs module** (cached TTS, reads the key from `.env`). Voice used
  in our video: **"Liam"**. Reuse it (import it); don't modify it.
- `results/viz/courtside_60.mp4` — the final 90 s video (already uses ElevenLabs narration + an ElevenLabs music bed).

## 1. What you build: "COURTSIDE Voice" — the strategy speaks

Make ElevenLabs a working part of the trading system, not just a voiceover. **Scope is deliberately small (about 2-3 hours of agent work):** two pieces, in priority order:

### 1a. Live call announcer (must have)
`sponsors/elevenlabs/announcer.py`
- Input: a stream of engine events. Two modes:
  - `--replay results/engine/online_events_L4.jsonl` (default for demos; plays the real calls at their real timing, optionally sped up),
  - `--follow <path.jsonl>` (tails a JSONL file that a running engine appends to; same schema).
- For each MISS call: speak a short line like **"Miss. Called three hundred twenty-five milliseconds early."**; for a paper
  fill (from `demo_run.json` / `e2e/trace.jsonl` rows): **"Buying player A at forty-one cents. Paper."**; for a risk event
  (feed stale / kill switch in `e2e/trace.jsonl` if present): **"Feed stale. Trading paused."**
- Latency matters (that is our whole thesis): **pre-generate** every line template with ElevenLabs once and cache the audio
  (numbers spoken as words: generate a small library — "Miss.", "Called", "<n> milliseconds early" for n in the leads that
  occur, "Buying", prices 1..99 cents, player names that occur); at runtime only **play** cached clips (no network call on the
  hot path). Measure and print the event -> audio-start latency (target < 50 ms).
- Use the ElevenLabs streaming / low-latency model where it helps (e.g. `eleven_flash_v2_5` or `eleven_turbo_v2_5` for short
  lines; keep "Liam" for brand consistency). Document which model and why.
- Playback: `afplay` on macOS or `simpleaudio`/`sounddevice` (add to `sponsors/elevenlabs/requirements.txt`, not the main one).

### 1b. Demo clip for the prize (must have)
`sponsors/elevenlabs/out/courtside_voice_demo.mp4` (30–60 s): take `results/engine/engine_live_demo.mp4` (or the CV clips in
`results/viz/v60_assets/clips/` if present) and mux in the announcer's audio at the exact call frames (ffmpeg), plus a short
title card "COURTSIDE Voice · powered by ElevenLabs". Show the measured event->audio latency on screen.

## 2. Rules (hard)
- **Folder ownership: you may only create/edit files under `sponsors/elevenlabs/`** (code, README, requirements, outputs ≤ 40 MB;
  put larger media in `sponsors/elevenlabs/out/` and gitignore it via `sponsors/elevenlabs/.gitignore`). Do NOT edit anything else
  (no edits to engine/, scripts/, docs/, results/, README.md, requirements.txt). That guarantees zero merge conflicts.
- **API key:** get your own free ElevenLabs access via the ElevenLabs Discord bot (see gqhacks Hacker Guide) or use the team
  key Ojasva gives you privately. Put it ONLY in `.env` at the repo root as `ELEVENLABS_API_KEY=...` (already gitignored).
  Never print it, log it, commit it, or paste it into chat/issues. `scripts/tts_elevenlabs.py` reads it for you.
- **Honesty:** paper only; never say we traded real money, received live match video, or bought a licensed feed. Spoken
  lines say "paper" where a trade is mentioned. Use only our own text; no voice cloning of real people.
- **Commits:** plain messages, **no "Co-Authored-By" / AI-attribution trailers** (team rule).

## 3. Setup
```bash
git clone https://github.com/OjasMishra32/computervisionpredictivetabletennismoneymachineouuushiii courtside && cd courtside
git checkout -b sponsor/elevenlabs
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r sponsors/elevenlabs/requirements.txt  # after you create it
echo 'ELEVENLABS_API_KEY=<your key>' >> .env   # never commit
.venv/bin/python scripts/tts_elevenlabs.py --voices        # sanity check: lists voices
```
`brew install ffmpeg` if missing. Python 3.12+ works; the repo was built on 3.14.

## 4. Hand back (no merge conflicts)
- Push your branch: `git push origin sponsor/elevenlabs` and open a PR titled "ElevenLabs: COURTSIDE Voice".
- Do NOT merge or rebase main into your branch (main's history gets rewritten tonight for a clean-up). Ojasva copies your
  folder onto main with `git checkout sponsor/elevenlabs -- sponsors/elevenlabs`.
- In the PR description paste: what you built, how to run it (3 commands), measured event->audio latency, ElevenLabs models
  used, characters used, and the Devpost text below filled in.

## 5. Definition of done
- [ ] `python sponsors/elevenlabs/announcer.py --replay results/engine/online_events_L4.jsonl --speed 4` speaks the calls in
      sync, prints event->audio latency stats (p50/p90), works with no network after the cache is built.
- [ ] `sponsors/elevenlabs/out/courtside_voice_demo.mp4` (30–60 s) exists and looks/sounds clean.
- [ ] `sponsors/elevenlabs/README.md`: what, why (latency thesis), how to run, models, measured latency, honesty notes.
- [ ] No key anywhere in git (`git grep -n sk_` returns nothing).

## 6. Devpost text (fill in and give to Ojasva)
**ElevenLabs — COURTSIDE Voice.** Our trading system talks. When the computer-vision engine calls a tennis/table-tennis
point before the ball lands, COURTSIDE announces it out loud in ElevenLabs' "Liam" voice — "Miss, called 325 ms early" —
and narrates paper fills and risk alerts. Because speed is our whole edge, every phrase is pre-generated with ElevenLabs
(<model>) and cached, so the alert starts <N> ms after the event. ElevenLabs also voices our 90-second demo video (narration
and music bed). Paper trading only.
