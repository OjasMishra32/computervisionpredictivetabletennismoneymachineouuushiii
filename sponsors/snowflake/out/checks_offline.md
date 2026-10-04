# COURTSIDE Warehouse: paper numbers reproduced in SQL

Engine: **DuckDB (offline check of the SQL, not the reported run)** · run 2026-10-04 05:06 UTC · 1.5 s · queries: `sponsors/snowflake/queries.sql`

**62 / 62 paper numbers reproduced** (20 / 20 recomputed in SQL from rows, 42 / 42 looked up from stored metrics). A number passes when the SQL value agrees with the paper's source value to 2 decimals, or to the source's own precision if coarser.

| ✓ | paper key | paper prints | source value | SQL value | matched on | kind | query |
|---|---|---|---|---|---|---|---|
| ✓ | `sc.cal.is.v05.c` | +1.21 | 1.211 | 1.2106 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.cal.is.v05.sr` | 15.5 | 15.5 | 15.5003 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.cal.is.v05.usd` | +$133 | 133.26 | 133.2588 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.cal.is.v1.c` | +1.11 | 1.113 | 1.113 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.cal.is.v1.sr` | 11.9 | 11.95 | 11.9538 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.cal.is.v1.usd` | +$94 | 94.35 | 94.3466 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.cal.is.v3.c` | −0.79 | -0.789 | -0.7891 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.cal.is.v3.sr` | −1.4 | -1.38 | -1.3844 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.cal.is.v3.usd` | −$6 | -5.92 | -5.9173 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.cal.oos.v05.c` | +0.82 | 0.817 | 0.8172 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.cal.oos.v05.sr` | 12.2 | 12.16 | 12.1576 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.cal.oos.v05.usd` | +$81 | 81.35 | 81.3485 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.cal.oos.v1.c` | +0.66 | 0.655 | 0.6546 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.cal.oos.v1.sr` | 8.8 | 8.85 | 8.8494 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.cal.oos.v1.usd` | +$57 | 56.59 | 56.5929 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.cal.oos.v3.c` | −1.47 | -1.466 | -1.4657 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.cal.oos.v3.sr` | −2.4 | -2.35 | -2.3507 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.cal.oos.v3.usd` | −$11 | -11.38 | -11.384 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.pre.is.v05.c` | +0.61 | 0.613 | 0.6131 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.pre.is.v05.sr` | 4.0 | 4 | 3.999 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.pre.is.v05.usd` | +$28 | 28.43 | 28.4291 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.pre.is.v1.c` | +0.40 | 0.401 | 0.401 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.pre.is.v1.sr` | 2.1 | 2.15 | 2.1527 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.pre.is.v1.usd` | +$15 | 14.78 | 14.7804 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.pre.is.v3.c` | −1.35 | -1.349 | -1.3493 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.pre.is.v3.sr` | −2.6 | -2.59 | -2.5945 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.pre.is.v3.usd` | −$13 | -12.68 | -12.6811 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.pre.oos.v05.c` | −0.02 | -0.018 | -0.0178 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.pre.oos.v05.sr` | 2.1 | 2.14 | 2.1411 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.pre.oos.v05.usd` | +$15 | 15.16 | 15.1644 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.pre.oos.v1.c` | −0.38 | -0.383 | -0.3826 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.pre.oos.v1.sr` | 0.3 | 0.34 | 0.3444 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.pre.oos.v1.usd` | +$4 | 4.35 | 4.3454 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.pre.oos.v3.c` | −1.69 | -1.69 | -1.6902 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.pre.oos.v3.sr` | −2.6 | -2.58 | -2.576 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `sc.pre.oos.v3.usd` | −$13 | -12.67 | -12.6675 | source | lookup | sharpe_and_pnl_by_feed_delay |
| ✓ | `cv.cal.be.is` | 2.23 | 2.23 | 2.2296 | source | recomputed | breakeven_feed_delay |
| ✓ | `cv.cal.be.oos` | 2.14 | 2.14 | 2.1402 | source | recomputed | breakeven_feed_delay |
| ✓ | `cv.pre.be.is` | 1.09 | 1.089 | 1.0886 | source | recomputed | breakeven_feed_delay |
| ✓ | `cv.pre.be.oos` | 1.01 | 1.014 | 1.0144 | source | recomputed | breakeven_feed_delay |
| ✓ | `cv.stc.be.is` | 0.34 | 0.338 | 0.3385 | source | recomputed | breakeven_feed_delay |
| ✓ | `cv.stc.be.oos` | 0.29 | 0.295 | 0.295 | source | recomputed | breakeven_feed_delay |
| ✓ | `capcv.half.is` | $73,000 | 73,288 | 73,288.5583 | printed | recomputed | capital_where_sharpe_halves |
| ✓ | `capcv.half.is.day` | $183 | 183.4 | 183.4468 | source | recomputed | capital_where_sharpe_halves |
| ✓ | `capcv.half.oos` | $40,000 | 40,245 | 40,245.0601 | source | recomputed | capital_where_sharpe_halves |
| ✓ | `capcv.half.oos.day` | $68 | 67.5 | 67.472 | source | recomputed | capital_where_sharpe_halves |
| ✓ | `capcv.halfall.is` | $165,000 | 164,685 | 164,684.2422 | printed | recomputed | capital_where_sharpe_halves |
| ✓ | `capcv.halfall.is.day` | $517 | 517.2 | 517.2427 | source | recomputed | capital_where_sharpe_halves |
| ✓ | `capcv.halfall.oos` | $97,000 | 96,926 | 96,925.7614 | source | recomputed | capital_where_sharpe_halves |
| ✓ | `capcv.halfall.oos.day` | $278 | 277.8 | 277.773 | source | recomputed | capital_where_sharpe_halves |
| ✓ | `e2e.margin` | 881 | 881.406 | 881.4052 | source | recomputed | pipeline_latency_budget |
| ✓ | `e2e.n` | 24 | 24 | 24 | source | recomputed | pipeline_latency_budget |
| ✓ | `e2e.net` | 65 | 64.506 | 64.5051 | source | recomputed | pipeline_latency_budget |
| ✓ | `e2e.ours` | 54 | 54.13 | 54.1305 | source | recomputed | pipeline_latency_budget |
| ✓ | `e2e.p99` | 2,218 | 2,218.466 | 2,218.4663 | source | recomputed | pipeline_latency_budget |
| ✓ | `e2e.total` | 2,119 | 2,118.595 | 2,118.5948 | source | recomputed | pipeline_latency_budget |
| ✓ | `v2.is.c` | +1.38 | 1.3815 | 1.3815 | source | lookup | v2_backtest_headline |
| ✓ | `v2.is.dd` | −2.0% | -2.012 | -2.012 | source | lookup | v2_backtest_headline |
| ✓ | `v2.is.sr` | 14.5 | 14.4832 | 14.4832 | source | lookup | v2_backtest_headline |
| ✓ | `v2.oos.c` | +0.60 | 0.5987 | 0.5987 | source | lookup | v2_backtest_headline |
| ✓ | `v2.oos.dd` | −2.1% | -2.0631 | -2.0631 | source | lookup | v2_backtest_headline |
| ✓ | `v2.oos.sr` | 6.7 | 6.6676 | 6.6676 | source | lookup | v2_backtest_headline |

Matched on *printed*: the SQL value rounds to the number the paper prints but differs from the stored source value by more than 2 decimals (`capcv.half.is` 73,288.5583 vs 73,288, `capcv.halfall.is` 164,684.2422 vs 164,685).
For the capacity figures this is input rounding, not a different rule: `results/capacity/cv_cells.csv` stores Sharpe to 4 decimals, while `capacity.json` was computed from unrounded values. The paper's own rule (`scripts/capacity_study.py::capacity_answer`) run on the same CSV gives the SQL value to the cent.

## Descriptive queries

### pipeline_waterfall

Q6. Descriptive: median milliseconds per pipeline stage over the 24 complete traces, in order (the waterfall).

|   STEP | STAGE                            |   P50_MS |
|-------:|:---------------------------------|---------:|
|      1 | sender: frame into encoder       |     2.22 |
|      2 | encode + WHIP + RTP in           |     6.41 |
|      3 | H.264 decode + handoff           |     1.09 |
|      4 | prep + queue + detector          |    39.92 |
|      5 | tracker + features + classifier  |     2.43 |
|      6 | strategy rule (fair value, edge) |     0.09 |
|      7 | risk check                       |     0.03 |
|      8 | unsigned order built             |     0.02 |
|      9 | network one-way (RTT/2)          |    64.51 |
|     10 | venue order delay                |  1000.00 |

### cv_calls_by_lead

Q7. Descriptive: the real-time CV engine's 172 calls (NVIDIA L4, table-tennis test footage) by how early they came before the predicted bounce. These calls carry no ground-truth labels, so this is a profile, not precision.

| CALL   |   BUCKET | LEAD_BEFORE_BOUNCE   |   N_CALLS |   MEDIAN_EMIT_LATENCY_MS |   MEAN_P_MISS |
|:-------|---------:|:---------------------|----------:|-------------------------:|--------------:|
| BOUNCE |        1 | 0-25 ms              |        21 |                     6.84 |          0.19 |
| BOUNCE |        2 | 25-50 ms             |       139 |                     6.92 |          0.21 |
| MISS   |        1 | 0-25 ms              |         3 |                     7.04 |          0.99 |
| MISS   |        2 | 25-50 ms             |         4 |                     7.19 |          0.99 |
| MISS   |        3 | 50-100 ms            |         5 |                     7.05 |          0.99 |

### clob_sample_profile

Q8. Descriptive: the 10-minute recorded Polymarket book sample (Oct 3, 11:23-11:33 UTC, public websocket). Server-stamp-to-receive lag per message type (includes the recording laptop's clock offset) and the median moneyline spread. A mechanics demo, not evidence of an edge.

| EVENT           |   N_ROWS |   N_MESSAGES |   MEDIAN_SERVER_TO_RECEIVE_MS |   P90_SERVER_TO_RECEIVE_MS |   MEDIAN_MONEYLINE_SPREAD_C |
|:----------------|---------:|-------------:|------------------------------:|---------------------------:|----------------------------:|
| pc              |   278874 |       139437 |                         64.00 |                    1200.70 |                        1.00 |
| b               |    50184 |          992 |                         69.00 |                    3148.00 |                      nan    |
| t               |      366 |          366 |                         65.00 |                    1368.50 |                      nan    |
| market_resolved |        6 |            6 |                        nan    |                     nan    |                      nan    |


Every P&L above is paper (simulated) trading on public data; nothing was traded. Sources: `results/tier0/latency_sweep.csv`, `results/capacity/cv_cells.csv`, `results/e2e/trace.jsonl`, `results/v2/*.json`, `results/engine/online_events_L4.jsonl`, `tests/fixtures/live_sample.jsonl.gz`; paper numbers from `results/paper/numbers.json`.
