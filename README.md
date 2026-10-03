# COURTSIDE

**Who gets paid in the seconds after a tennis point, and what it takes to be first.**
Gator Quant Hacks 2026 · Systematic Trading track · Quant note: [`docs/NOTE.pdf`](docs/NOTE.pdf)

Every tennis point moves a prediction market. We measured, on every resolved Polymarket ATP/WTA
singles moneyline from Oct 2025 to Oct 2026 (13,084 matches, $2.84B traded), who makes and who loses
money around those moves. Then we built a strategy around the answer and measured how early ball
tracking can know a point is over.

| | Result |
|---|---|
| Chasing the move after a point (H1) | loses 1.5–2.1¢/share in and out of sample |
| Live prices | calibrated within ~1¢ (H2: no slow-money edge) |
| **Fast tier** (wallets trading ≤3 s after a point) | beat the market in **11/11 months**, walk-forward; everyone else loses ~1¢ |
| **v2 strategy** (causal window, risk sizing, fee-aware wallets, 100-share net cap, hold to resolution) | **in sample +1.38¢/share [1.17, 1.59], Sharpe 14.5, max DD −2.0%, 7/7 months** (still +0.38¢ at +1 tick slippage); burned OOS +0.60¢ [0.09, 1.13], Sharpe 6.7, but ≈0 at +½ tick: profitable only at the front of the queue. Blind forward test: `results/v2/forward.json` |
| Ball tracking | Hawk-Eye-class physics: ±2.4 cm landing call 100 ms before the bounce; real 120 fps video: misses called 50 ms early, 11/11 correct |
| Latency | the book reprices 1.2 s *before* the official point stamp; ESPN/Polymarket/WTA feeds are 27–43 s behind; Kalshi leads Polymarket ~2 s |

Integrity trail: `HYPOTHESIS.md` (pre-registered, commit `7232986`) → `DEVIATIONS.md` (every change,
including failed hypotheses) → `HYPOTHESIS_V2.md` (v2 frozen before its forward test) →
`results/oos_peeks.log` and `results/forward_peeks.log` (every look at held-out data).

## Reproduce

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/fetch_polymarket.py   # public Polymarket APIs, no keys; ~1-2 h, cached in data/
bash reproduce.sh                               # every number and figure in the note -> results/
```

`reproduce.sh` runs `run_all.py --oos` (H1–H6, calibration, tiers, the walk-forward fast tier),
`scripts/v2_causal.py` (v2 on in-sample + burned OOS, with slippage stress) and the figures. The v2 forward test is a one-shot:
`python scripts/forward_test.py` (pre-registered window; logs every run). Tests: `pytest tests`.

Other pieces:

| Command | What |
|---|---|
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
| `src/polymarket.py`, `src/tape.py` | public API client; universe, locked 80/20 split, side-of-book classification |
| `src/strategies.py`, `src/backtest.py` | H1, H2, H5 and portfolio statistics |
| `src/tiers.py`, `src/fasttier.py` | markouts by seconds since the score event; walk-forward fast tier (H6) |
| `src/v2.py` | the frozen v2 rule, runnable on any period |
| `src/markov.py` | exact point-level tennis Markov model (fair value, leverage) |
| `src/hawkeye.py` | drag + Magnus ball flight, 340 fps tracking noise, early out calls |
| `src/paper.py` | replays recorded live books; orders wait the venue delay + latency, then walk the book |
| `src/tracking/`, `src/tennis_tracking/` | ball tracking on real footage (HiPerGator) |
| `results/` | every reported number (`summary.json`, `v2/`), figures, demo videos |

## Data and licences

Polymarket Gamma/Data/CLOB APIs and the Kalshi public market-data API (no keys). OpenTTGames (OSAI,
CC BY-NC-SA 4.0); the demo clips in `results/tracking/demo/` are derived from it under the same
licence. The TrackNet tennis dataset and pretrained detectors are cited in `src/tennis_tracking/README.md`
(no broadcast frames are included). No API keys or licensed raw data are committed; raw data lives in
`data/` (gitignored). The code only reads public data and never places an order.
