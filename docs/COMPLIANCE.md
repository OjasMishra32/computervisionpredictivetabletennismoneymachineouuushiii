# Systematic Trading Track: compliance checklist

Each requirement in the Gator Quant Hacks 2026 Systematic Trading Track brief, and where this repo
meets it.

## Submission checklist (from the brief)

| Requirement | Where |
|---|---|
| Quant note as a PDF, ≤ 5 pages excluding references and appendix | `docs/NOTE.pdf` (5 pages, references inline in §8) |
| In-sample and out-of-sample results reported separately, net of costs | `docs/NOTE.md` Table 1 (H1–H6) and Table 2 (v2: IS / burned OOS / forward); `results/summary.json`, `results/v2/causal.json` |
| Sharpe, max drawdown, turnover and an equity curve | Table 2 (Sharpe, max DD); §7 (turnover ~93× a year); Fig. 2 / `results/figures/fig6_v2.png` (equity) |
| Risk management and liquidity/capacity sections | `docs/NOTE.md` §6 and §7 |
| Number of strategy variants tested disclosed | §8: 44 (H1–H6) + 3,342 across the v2 lenses, all in `results/` and `research/v2/` |
| Public GitHub repo with a README and a dependency file | `README.md`, `requirements.txt` |
| One command or notebook reproduces the headline numbers | `bash reproduce.sh` (after `scripts/fetch_polymarket.py`) |
| No API keys or licensed raw data committed | `.gitignore` excludes `data/` and `.env`; only public Polymarket/Kalshi market data is used; demo clips are CC BY-NC-SA 4.0 (OpenTTGames), credited |
| All team members listed on Devpost | Team action |

## Method rules (from the brief)

| Rule | How we meet it |
|---|---|
| Write the economic hypothesis before seeing results | `HYPOTHESIS.md`, commit `7232986` (H1–H4); H5/H6 are labelled post-hoc in `DEVIATIONS.md`; v2 is pre-registered in `HYPOTHESIS_V2.md` |
| Out-of-sample = last 20% or last 2 years, whichever is shorter | Last 20% of matches by start time (from 2026-08-25 14:15 UTC); split in `src/tape.py` |
| Evaluate OOS once; report every peek | `results/oos_peeks.log`: v1 opened once; later v2 runs on that window are labelled non-blind |
| Lag every signal; no same-bar signal and fill | Fills only at later prints on the side we would hit; the 0–3 s window is measured from jump *detection* (D9); the venue's 1 s order delay plus our latency are applied before any fill |
| Point-in-time universe, no survivorship | Every resolved market in the window, winners and losers, pulled from the venue's own event list |
| Realistic costs, and what happens when costs double | Each match's own taker fee (`rate·q(1−q)`); traded spreads from side-of-book prints; slippage stress at +½ and +1 tick (Table 2) |
| Show nearby parameters work (plateau, not a spike) | Sizing settings all have per-share CIs > 0, with Sharpe 9.9–16.8; full grids in `research/v2/*/` |
| Report max DD, skew, worst month next to Sharpe; explain a Sharpe > 3 | Table 2 and `results/v2/causal.json`. NOTE §4 explains the high Sharpe (many small, independent, capped bets) and §8 sets it against a luck benchmark (≈ 4.8 for the trials run) |
| Break results down by period/regime | By month (Fig. 2, `results/fasttier_walkforward_is.csv`) and by venue regime (fee/delay) in `DEVIATIONS.md` D6 |
| Regress returns on known factors | `scripts/factor_regression.py`: daily alpha +0.79% (t = 8.5); market, size, value and momentum betas all insignificant (largest t = 1.33); R² = 3% |
| Size by liquidity; estimate capacity in dollars | §7: live depth, stale depth per point, fast-tier volume, v2 notional; v2 caps at $1k/order and 100 shares net per match |
| Limits per position and rules for cutting size | §6: per-order and per-match caps, daily stop, a size-halving rule on trailing edge, kill switches |
| Every source cited | `README.md` "Data and licences"; NOTE §2 and §8 |

## Extra integrity measures (beyond the brief)
- Adversarial verifier reports for every optimisation lens and for v2 (`research/v2/*/verify_*`, `research/v2/verify_v2/`).
- A blind test on 11,307 never-examined markets, pre-registered before any result (`research/v2/expand/PREREG.md`).
- A blind forward test on matches played after the pre-registration (`HYPOTHESIS_V2.md`, `scripts/forward_test.py`, logged in `results/forward_peeks.log`).
- The code is read-only and never places an order.
