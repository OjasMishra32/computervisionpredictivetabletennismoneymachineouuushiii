# COURTSIDE

**Who gets paid in the seconds after a tennis point, and how ball tracking gets you there first.**
Gator Quant Hacks 2026, Systematic Trading track.

In-play tennis prices on Polymarket move in jumps, one per point. We measured, on every resolved
ATP/WTA singles moneyline from Oct 2025 to Oct 2026, who makes and who loses money around those
jumps. We also measured how early ball tracking can know a point is over before the market does.

- `HYPOTHESIS.md`: pre-registered before any result (git commit `7232986`).
- `DEVIATIONS.md`: every change after that, with the reason, including the hypotheses that failed.
- Quant note: `docs/NOTE.pdf`.

## Reproduce

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/fetch_polymarket.py   # public Polymarket APIs, no keys; ~1-2 h, cached
.venv/bin/python run_all.py                     # in-sample results + figures -> results/
.venv/bin/python run_all.py --oos               # locked out-of-sample period (each run is logged)
```

Live order-book and score-feed recording (read-only; never places orders):

```bash
.venv/bin/python -m src.live_recorder --hours 6
.venv/bin/python -m src.h4_live
.venv/bin/python scripts/live_books.py
```

Ball tracking runs on HiPerGator (SLURM scripts in `hpg/`). See `src/tracking/README.md`
(table tennis, OpenTTGames 120 fps) and `src/tennis_tracking/README.md` (tennis broadcast).
The physics Monte Carlo for Hawk-Eye-class tracking is `src/hawkeye.py`.

## Layout

| path | what |
|---|---|
| `src/polymarket.py` | event catalogue, trade tapes, price history (public endpoints, cached) |
| `src/tape.py` | universe, the locked 80/20 time split, side-of-book classification of prints |
| `src/strategies.py` | H1 jump-follow, H2 favourite band, H5 post-event maker |
| `src/tiers.py` | markouts of every taker print by seconds since the score event |
| `src/fasttier.py` | H6 walk-forward: wallets that win right after points, picked on past data only |
| `src/markov.py` | exact point-level tennis Markov model: fair value and point leverage |
| `src/hawkeye.py` | drag + Magnus ball flight, 340 fps tracking noise, early in/out calls |
| `src/live_recorder.py`, `src/h4_live.py` | live book + score feed, book-vs-feed latency |
| `run_all.py` | one command for every number in the note |

## Data sources

- Polymarket Gamma, Data and CLOB APIs (public, keyless): events, trade tapes, order books, sports feed.
- OpenTTGames (OSAI, CC BY-NC-SA 4.0): 120 fps table-tennis video with labeled bounces.
- TrackNet tennis dataset and open-source detectors (see `src/tennis_tracking/README.md`).

No API keys or licensed data are committed. Raw data lives in `data/` (gitignored).
