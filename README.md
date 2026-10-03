> **Judges: start here.** Commands from the repo root (tested on Python 3.12 Linux and 3.14 macOS).
>
> | Command | What it does | Time |
> |---|---|---|
> | `bash run.sh setup` | makes `.venv`, installs `requirements.txt` | ~1-3 min |
> | `bash run.sh replay` | 10 min of recorded live Polymarket books (`tests/fixtures/live_sample.jsonl.gz`, public market data) through the paper trader and the engine's order books; no network | ~15 s |
> | `bash run.sh tests` | unit tests (vision tests too after `bash run.sh setup --full`) | ~2-7 min |
> | `bash run.sh data && bash run.sh reproduce` | public Polymarket crawl (no keys, resumable), then every number and figure in `docs/NOTE.pdf` | ~1-2 h + ~15 min |
>
> - A fresh clone has no market data: run `bash run.sh data` before `reproduce` or `money`. The full crawl-then-reproduce
>   chain was last run end to end on the authors' machine, not on a clean clone (`research/compliance/CLEAN_CLONE.md`).
> - The CV calls need `models/vision/frozen_call_model.pkl` (12 MB), which is not in git. `bash run.sh cv` still
>   detects and tracks the ball on the held-out clip, with calls disabled; `sbatch hpg/engine_vision.sbatch`
>   (HiPerGator) rebuilds the model.
> - Paper only: nothing here signs or sends an order. We bought no official ATP/WTA data feed and no trading result
>   uses one; free public score pages (WTA website, ESPN) were recorded only to time their lag.
> - Footage notice: the demo clips are OpenTTGames (OSAI) footage, adapted (overlays added), CC BY-NC-SA 4.0.
> - `bash run.sh help` lists the rest (live paper session, engine, vision, dashboard, money counter).

# COURTSIDE

**Who gets paid in the seconds after a tennis point, and what it takes to be first.**
Gator Quant Hacks 2026 · Systematic Trading track · Quant note: [`docs/NOTE.pdf`](docs/NOTE.pdf) (5 pages, 11 pt, 1 in margins)

Every tennis point moves a prediction market. We measured, on every resolved Polymarket ATP/WTA
singles moneyline from Oct 2025 to Oct 2026 (13,084 matches, $2.84B traded), who makes and who loses
money around those moves. Then we built a strategy around the answer and measured how early ball
tracking can know a point is over.

| | Result |
|---|---|
| Chasing the move after a point (H1) | loses 1.5–2.1¢/share in and out of sample |
| Live prices | calibrated within ~1¢ (H2: no slow-money edge) |
| **Fast tier** (wallets trading ≤3 s after a point) | beat the market in **11/11 months** (8 in sample, 3 out of sample), walk-forward; everyone else loses ~1¢ |
| v1 (copy the fast tier, $ sizing) | +1.16¢/share in sample; **lost $36k** on the held-out window (opened once, blind) |
| **v2 strategy** (causal window, risk sizing, fee-aware wallets, 100-share net cap, hold to resolution) | **in sample** +1.38¢/share [1.17, 1.59], Sharpe 14.5, max DD −2.0%, 7/7 months, +0.38¢ at +1 tick. **Burned OOS (non-blind, v2 was designed after v1's result):** +0.60¢ [0.09, 1.13], Sharpe 6.7; ≈0 at +½ tick; **negative with costs doubled** (fees ×2: −0.34¢; all costs ×2: −0.84¢) |
| Blind test of frozen v2 on 11,307 unseen markets | in-sample period +2.02¢ (pass); out-of-sample period +1.22¢ [−0.19, 2.65] (**fail**) |
| Blind forward test of v2 | pre-registered (`HYPOTHESIS_V2.md`); runs once on Oct 4 → `results/v2/forward.json` (not yet created) |
| Ball tracking | Hawk-Eye-class physics (assumed 340 fps): ±2.4 cm landing call 100 ms before the bounce; real 120 fps video: misses called 50 ms early, 11 of 11 calls correct (recall 27%) |
| Latency | the book reprices 1.2 s *before* the official point stamp; ESPN/Polymarket/WTA feeds are 27–43 s behind |

Rules checklist, item by item against the track page: [`docs/COMPLIANCE.md`](docs/COMPLIANCE.md).
Integrity trail: `HYPOTHESIS.md` (pre-registered, commit `7232986`) → `DEVIATIONS.md` (every change,
including failed hypotheses) → `HYPOTHESIS_V2.md` (v2 frozen before its forward test) →
`results/oos_peeks.log` (every look at held-out data; the note lists them) and `results/forward_peeks.log`
(created by the one forward run).

## Reproduce

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # Python 3.14
.venv/bin/python scripts/fetch_polymarket.py   # public Polymarket APIs, no keys; ~1-2 h, cached in data/
bash reproduce.sh                               # every number and figure in the note -> results/, docs/NOTE.pdf
.venv/bin/pytest tests                          # unit tests
```

`reproduce.sh` runs, in order:

| Step | Produces |
|---|---|
| `run_all.py --oos` | H1–H6, calibration, tiers, walk-forward fast tier, v1 (Table 1) → `results/summary.json` |
| `scripts/v2_causal.py` | v2 on in-sample + burned OOS with ½- and 1-tick slippage (Table 2) → `results/v2/causal.json` |
| `scripts/v2_cost_stress.py` | v2 with fees doubled and all costs doubled (Table 2) → `results/v2/cost_stress.json` |
| `scripts/note_metrics.py` | annualised return and volatility, turnover, skew, worst month, cost and edge in bps, holdout share, data gaps → `results/v2/note_metrics.json` |
| `scripts/v2_figures.py`, `factor_regression.py`, `leverage_stats.py` | Fig. 1, the factor regression, Markov leverage |
| `scripts/make_pdf.py` | `docs/NOTE.pdf` (needs Chrome or Chromium; skipped without failing if neither is installed) |

Things to know before running it:
- **Peek log.** On a fresh clone the first step builds the locked out-of-sample prints and appends one
  line to `results/oos_peeks.log`. That line records your run. Re-running on the same checkout appends
  nothing. `scripts/v2_burned_oos.py` (the superseded onset-window v2) appends a line on every run; it is
  not part of `reproduce.sh`.
- **Not regenerated by `reproduce.sh`** (outputs are committed): the rigor pack
  (`scripts/rigor_pack.py`, ~25 s; DSR, PBO, block bootstrap, daily sd and skew → `results/rigor/`; it
  rewrites `research/rigor/RESULTS.md`, whose verifier-corrections header is hand-written), the six v2
  lenses and verifiers (`research/v2/<lens>/`), the blind out-of-universe tests (`scripts/expand_test.py`,
  `scripts/lowloss_test.py`), and ball tracking on HiPerGator.
- **Live data cannot be re-downloaded.** The order-book and score-feed recordings of 2026-10-03 behind the
  latency and depth numbers (note §6) were made with `src/live_recorder.py` and live in `data/live*`
  (gitignored). The derived numbers are in `results/` and `research/v2/{latency,livefill,blocklag}/`.
- The v2 forward test is a one-shot: `python scripts/forward_test.py` (pre-registered window; logs every run).

## Run it live

```bash
.venv/bin/python scripts/live_paper.py
```

This paper-trades the frozen side-market maker (maker v1, `research/v2/maker/PREREG.md`) on whatever ATP, WTA and
Challenger matches are in play right now. It also runs a taker control that trades the same signal at our real
latency. The data is live: public Polymarket feeds, with no keys and no account. The orders are paper: nothing is
ever signed or sent. The terminal dashboard shows equity, P&L (realised, and marked to mid until resolution), open
quotes, the signals and a tape of fills for every book.
- **Options.** `--minutes N` stops quoting after N minutes, `--until 2026-10-04T11:30:00Z` stops at a given time,
  `--capital 10000` sets the starting capital, and `--no-dashboard` prints plain log lines instead.
- **No tennis on right now?** Replay recorded live books through the same engine:
  `.venv/bin/python scripts/live_paper.py --replay 'data/live_v2/clob_20261003_1123_20261003_1[12].jsonl.gz' --replay-from 2026-10-03T12:00:00Z --replay-minutes 60`
- **Output.** `results/live/` holds every event and fill plus a rolling `summary.json`. `data/live_maker/raw_*.jsonl.gz`
  holds every websocket message; `--replay` on that file re-runs a session exactly.
- **Before it quotes,** a warm-up checks the websocket's trade-side convention against data-api on 50 trades
  (about 10–20 minutes).
- **Pre-registered session.** It runs until 2026-10-04 11:30 UTC; see `results/live/SESSION.md`. Fill-model details:
  `research/v2/maker/DEVIATIONS_LIVE.md`. Tests: `pytest tests/test_live_paper.py`.

Other pieces:

| Command | What |
|---|---|
| `pip install -r requirements-extra.txt` | optional extras: tracking (torch, OpenCV, PyAV, scikit-learn) and the deck (python-pptx) |
| `bash scripts/serve_live.sh` then open http://localhost:8765 | COURTSIDE Live: order-book scoreboard vs ESPN |
| `python -m src.live_recorder --hours 6` | record live order books + Polymarket's sports feed (read-only) |
| `python -m src.h4_live` · `python scripts/live_books.py` | book-vs-feed latency · live depth, tennis vs table tennis |
| `python research/v2/livefill/livefill.py` | do passive exits fill on live books? (no: adversely selected) |
| `python research/v2/blocklag/blocklag.py` | tape timestamps vs true match time (median 1.98 s lag) |
| `python scripts/leverage_stats.py` | Markov point leverage per match |
| `python scripts/render_hawkeye_video.py` | Hawk-Eye-style replay video (`results/viz/courtside_replay.mp4`) |
| `python scripts/export_viz.py && python scripts/build_viz.py` | interactive visual (`docs/viz/courtside.html`) |
| `sbatch hpg/track_*.sbatch` (HiPerGator) | table-tennis tracking on OpenTTGames; see `src/tracking/README.md` |
| `sbatch hpg/tennis_*.sbatch` (HiPerGator) | tennis broadcast tracking; see `src/tennis_tracking/README.md` |
| `research/v2/<lens>/` | six optimisation lenses + two adversarial verifier reports each |

## Layout

| path | what |
|---|---|
| `src/polymarket.py`, `src/tape.py` | public API client; universe, locked 80/20 split (by match count), side-of-book classification |
| `src/strategies.py`, `src/backtest.py` | H1, H2, H5 and portfolio statistics |
| `src/tiers.py`, `src/fasttier.py` | markouts by seconds since the score event; walk-forward fast tier (H6) |
| `src/v2.py` | the frozen v2 rule, runnable on any period |
| `src/markov.py` | exact point-level tennis Markov model (fair value, leverage) |
| `src/hawkeye.py` | drag + Magnus ball flight, 340 fps tracking noise (assumed), early out calls |
| `src/paper.py` | replays recorded live books; orders wait the venue delay + latency, then walk the book |
| `engine/` | paper-only engine: v2 risk limits, $1,000 daily stop, kill switches (`engine/risk/limits.py`) |
| `src/tracking/`, `src/tennis_tracking/` | ball tracking on real footage (HiPerGator) |
| `results/` | every reported number (`summary.json`, `v2/`, `rigor/`), figures, demo videos |

## Data, sources and licences

- **Market data:** Polymarket Gamma, Data and CLOB APIs and its sports websocket; the Kalshi public
  market-data API. Public, no keys. Score feeds for the latency study: ESPN's public scoreboard and the
  WTA public API, read live; only derived timings (scores and timestamps) are committed.
- **Factors:** Kenneth R. French Data Library (Fama–French market, size, value; momentum).
- **Video:** OpenTTGames (OSAI, CC BY-NC-SA 4.0); the demo clips in `results/tracking/demo/` are derived
  from it under the same licence. The TrackNet tennis dataset (Huang et al. 2019) is used for evaluation
  only; no broadcast frames are included.
- **Pre-existing components** (not built during the event; disclosed per the Terms §14.2): BlurBall
  pretrained weights and code (MIT) on WASB-SBDT (MIT), used zero-shot for table-tennis ball detection;
  TrackNet weights and TennisProject / TennisCourtDetector code (no licence file; used unmodified for
  evaluation, not vendored or redistributed). Details in `src/tracking/README.md` and
  `src/tennis_tracking/README.md`. Everything else was written during the event, with AI coding
  assistants; commits carry a `Co-Authored-By` line.
- No API keys or licensed raw data are committed; raw data lives in `data/` (gitignored). The code only
  reads public data and never places an order.
