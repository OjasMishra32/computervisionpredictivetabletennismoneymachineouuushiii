# Independent re-derivation of the headline numbers

Run 2026-10-04 03:39 local on `ian_check` · numbers file generated 2026-10-04T07:18:57+00:00 · engine DuckDB 1.5.6

**146 headline numbers (154 checks, some by two routes) re-derived in SQL from row-level files: 136 ✓, 10 ✗.**

Each number is recomputed by a SQL query in [`sponsors/snowflake/sql/`](../sql/) from row-level files in git (daily P&L per seed, per-seed sweep cells, trade ledgers, per-seed size cells), without the team's Python. A number matches when the SQL value rounds to what the paper prints, at the printed precision (percent printed from a fraction counts as x100). The definition each query uses is in the last column.

## Mismatches

| paper key | printed | SQL value | what differs | SQL file |
|---|---|---|---|---|
| `cv.cal.is.sr` | 11.9 | 11.9538 | double rounding: rows give 11.9538 -> prints 12.0; the stored 11.95 was already rounded and rounding it again gives 11.9 | 02_cv_cells_seeds.sql |
| `cv.cal.oos.c` | +0.66 | 0.6546 | double rounding: rows give 0.6546 -> prints 0.65; the stored 0.655 was already rounded and rounding it again gives 0.66 | 02_cv_cells_seeds.sql |
| `cv.pre.is.sr` | 2.1 | 2.1527 | double rounding: rows give 2.1527 -> prints 2.2; the stored 2.15 was already rounded and rounding it again gives 2.1 | 02_cv_cells_seeds.sql |
| `sc.cal.is.v1.cci` | [0.85, 1.38] | [0.8494, 1.3745] | double rounding: rows give 1.3745 -> prints 1.37; the stored 1.375 was already rounded and rounding it again gives 1.38 | 02_cv_cells_seeds.sql |
| `sc.cal.is.v1.sr` | 11.9 | 11.9538 | double rounding: rows give 11.9538 -> prints 12.0; the stored 11.95 was already rounded and rounding it again gives 11.9 | 02_cv_cells_seeds.sql |
| `sc.cal.oos.v1.c` | +0.66 | 0.6546 | double rounding: rows give 0.6546 -> prints 0.65; the stored 0.655 was already rounded and rounding it again gives 0.66 | 02_cv_cells_seeds.sql |
| `sc.pre.is.v1.sr` | 2.1 | 2.1527 | double rounding: rows give 2.1527 -> prints 2.2; the stored 2.15 was already rounded and rounding it again gives 2.1 | 02_cv_cells_seeds.sql |
| `sc.pre.oos.v1.cci` | [−2.08, 1.21] | [-2.0826, 1.2047] | double rounding: rows give 1.2047 -> prints 1.20; the stored 1.205 was already rounded and rounding it again gives 1.21 | 02_cv_cells_seeds.sql |
| `cv.cal.is.sr` | 11.9 | 11.9538 | double rounding: rows give 11.9538 -> prints 12.0; the stored 11.95 was already rounded and rounding it again gives 11.9 | 03_cv_daily_sharpe.sql |
| `cv.pre.is.sr` | 2.1 | 2.1527 | double rounding: rows give 2.1527 -> prints 2.2; the stored 2.15 was already rounded and rounding it again gives 2.1 | 03_cv_daily_sharpe.sql |
| `capcv.half.oos.day` | $68 | 67.472 | double rounding: rows give 67.4720 -> prints 67; the stored 67.5 was already rounded and rounding it again gives 68 | 06_capacity_seeds.sql |
| `capcv.pre.sr0.oos` | 0.8 | 0.8504 | double rounding: rows give 0.8504 -> prints 0.9; the stored 0.85 was already rounded and rounding it again gives 0.8 | 06_capacity_seeds.sql |

## All re-derived numbers

| paper key | printed | SQL value | match | SQL file | definition |
|---|---|---|---|---|---|
| `calc.is.mean` | $196.24 | 196.2414 | ✓ | 01_v2_daily.sql | mean daily P&L |
| `calc.oos.mean` | $92.19 | 92.1884 | ✓ | 01_v2_daily.sql | mean daily P&L |
| `tab.v2.is.usd` | +$196 | 196.2414 | ✓ | 01_v2_daily.sql | mean daily P&L |
| `tab.v2.oos.usd` | +$92 | 92.1884 | ✓ | 01_v2_daily.sql | mean daily P&L |
| `v2.is.days` | 206 | 206 | ✓ | 01_v2_daily.sql | calendar days |
| `v2.is.dd` | −2.0% | -2.012 | ✓ | 01_v2_daily.sql | max drawdown of cumulative P&L / capital, % |
| `v2.is.kurt` | 4.30 | 4.2955 | ✓ | 01_v2_daily.sql | Pearson kurtosis = excess kurtosis + 3 |
| `v2.is.pnl` | +$40,426 | 40,425.7192 | ✓ | 01_v2_daily.sql | sum of daily P&L |
| `v2.is.ret` | 253% | 253.0816 | ✓ | 01_v2_daily.sql | mean daily P&L x 365 / capital, % |
| `v2.is.skew` | +0.53 | 0.5345 | ✓ | 01_v2_daily.sql | sample skewness of daily P&L |
| `v2.is.sr` | 14.5 | 14.4832 | ✓ | 01_v2_daily.sql | mean / sample sd of daily P&L x sqrt(365) |
| `v2.is.vol` | 17.5% | 17.4742 | ✓ | 01_v2_daily.sql | sd of daily P&L x sqrt(365) / capital, % |
| `v2.is.worstday` | −1.9% | -1.946 | ✓ | 01_v2_daily.sql | worst day / capital, % |
| `v2.is.worstmonth` | +$2,543 | 2,542.5647 | ✓ | 01_v2_daily.sql | worst calendar month (dates + 1 day) |
| `v2.oos.days` | 40 | 40 | ✓ | 01_v2_daily.sql | calendar days |
| `v2.oos.dd` | −2.1% | -2.0631 | ✓ | 01_v2_daily.sql | max drawdown of cumulative P&L / capital, % |
| `v2.oos.kurt` | 3.26 | 3.2597 | ✓ | 01_v2_daily.sql | Pearson kurtosis = excess kurtosis + 3 |
| `v2.oos.pnl` | +$3,688 | 3,687.5359 | ✓ | 01_v2_daily.sql | sum of daily P&L |
| `v2.oos.ret` | 148% | 147.8804 | ✓ | 01_v2_daily.sql | mean daily P&L x 365 / capital, % |
| `v2.oos.skew` | +0.33 | 0.3256 | ✓ | 01_v2_daily.sql | sample skewness of daily P&L |
| `v2.oos.sr` | 6.7 | 6.6676 | ✓ | 01_v2_daily.sql | mean / sample sd of daily P&L x sqrt(365) |
| `v2.oos.vol` | 22.2% | 22.1791 | ✓ | 01_v2_daily.sql | sd of daily P&L x sqrt(365) / capital, % |
| `v2.oos.worstday` | −2.1% | -2.0631 | ✓ | 01_v2_daily.sql | worst day / capital, % |
| `v2.oos.worstmonth` | −$434 | -434.1531 | ✓ | 01_v2_daily.sql | worst calendar month (dates + 1 day) |
| `cv.cal.is.c` | +1.11 | 1.113 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of cents/share, 1 s |
| `cv.cal.is.dd` | −1.6 | -1.5857 | ✓ | 02_cv_cells_seeds.sql | mean drawdown / mean capital, %, 1 s |
| `cv.cal.is.sr` | 11.9 | 11.9538 | ✗ | 02_cv_cells_seeds.sql | 20-seed mean of Sharpe, 1 s |
| `cv.cal.is.tpd` | 65 | 64.9456 | ✓ | 02_cv_cells_seeds.sql | mean trades / mean days, 1 s |
| `cv.cal.is.usd` | +$94 | 94.3466 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of $/day, 1 s |
| `cv.cal.is.worstday` | −$223 | -223.4235 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of the worst day, 1 s |
| `cv.cal.is.wrong` | 12% | 0.1208 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean share of trades on wrong calls, 1 s |
| `cv.cal.oos.c` | +0.66 | 0.6546 | ✗ | 02_cv_cells_seeds.sql | 20-seed mean of cents/share, 1 s |
| `cv.cal.oos.dd` | −1.6 | -1.6079 | ✓ | 02_cv_cells_seeds.sql | mean drawdown / mean capital, %, 1 s |
| `cv.cal.oos.sr` | 8.8 | 8.8495 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of Sharpe, 1 s |
| `cv.cal.oos.tpd` | 55 | 55.2975 | ✓ | 02_cv_cells_seeds.sql | mean trades / mean days, 1 s |
| `cv.cal.oos.usd` | +$57 | 56.5929 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of $/day, 1 s |
| `cv.cal.oos.worstday` | −$192 | -191.8843 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of the worst day, 1 s |
| `cv.cal.oos.wrong` | 16% | 0.1597 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean share of trades on wrong calls, 1 s |
| `cv.pre.is.c` | +0.40 | 0.401 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of cents/share, 1 s |
| `cv.pre.is.dd` | −6.6 | -6.5864 | ✓ | 02_cv_cells_seeds.sql | mean drawdown / mean capital, %, 1 s |
| `cv.pre.is.sr` | 2.1 | 2.1527 | ✗ | 02_cv_cells_seeds.sql | 20-seed mean of Sharpe, 1 s |
| `cv.pre.is.tpd` | 26 | 25.6189 | ✓ | 02_cv_cells_seeds.sql | mean trades / mean days, 1 s |
| `cv.pre.is.usd` | +$15 | 14.7804 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of $/day, 1 s |
| `cv.pre.is.worstday` | −$263 | -263.4989 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of the worst day, 1 s |
| `cv.pre.is.wrong` | 35% | 0.3484 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean share of trades on wrong calls, 1 s |
| `cv.pre.oos.c` | −0.38 | -0.3826 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of cents/share, 1 s |
| `cv.pre.oos.dd` | −5.3 | -5.2747 | ✓ | 02_cv_cells_seeds.sql | mean drawdown / mean capital, %, 1 s |
| `cv.pre.oos.sr` | 0.3 | 0.3444 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of Sharpe, 1 s |
| `cv.pre.oos.tpd` | 24 | 24.2863 | ✓ | 02_cv_cells_seeds.sql | mean trades / mean days, 1 s |
| `cv.pre.oos.usd` | +$4 | 4.3454 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of $/day, 1 s |
| `cv.pre.oos.worstday` | −$228 | -228.3848 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of the worst day, 1 s |
| `cv.pre.oos.wrong` | 47% | 0.4723 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean share of trades on wrong calls, 1 s |
| `sc.cal.is.v05.c` | +1.21 | 1.2106 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of net cents/share |
| `sc.cal.is.v05.cci` | [1.00, 1.42] | [1.0018, 1.4212] | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of the per-seed cents/share CI bounds |
| `sc.cal.is.v05.sr` | 15.5 | 15.5003 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of the per-seed Sharpe |
| `sc.cal.is.v05.uci` | [80, 168] | [79.9212, 167.5582] | ✓ | 02_cv_cells_seeds.sql | 2.5-97.5 % of the 20 seed $/day values |
| `sc.cal.is.v05.usd` | +$133 | 133.2588 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of $/day |
| `sc.cal.is.v1.c` | +1.11 | 1.113 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of net cents/share |
| `sc.cal.is.v1.cci` | [0.85, 1.38] | [0.8494, 1.3745] | ✗ | 02_cv_cells_seeds.sql | 20-seed mean of the per-seed cents/share CI bounds |
| `sc.cal.is.v1.sr` | 11.9 | 11.9538 | ✗ | 02_cv_cells_seeds.sql | 20-seed mean of the per-seed Sharpe |
| `sc.cal.is.v1.uci` | [51, 125] | [51.2972, 125.0108] | ✓ | 02_cv_cells_seeds.sql | 2.5-97.5 % of the 20 seed $/day values |
| `sc.cal.is.v1.usd` | +$94 | 94.3466 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of $/day |
| `sc.cal.is.v3.c` | −0.79 | -0.7891 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of net cents/share |
| `sc.cal.is.v3.cci` | [−2.26, 0.60] | [-2.2597, 0.5967] | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of the per-seed cents/share CI bounds |
| `sc.cal.is.v3.sr` | −1.4 | -1.3844 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of the per-seed Sharpe |
| `sc.cal.is.v3.uci` | [−24, 34] | [-23.9843, 34.235] | ✓ | 02_cv_cells_seeds.sql | 2.5-97.5 % of the 20 seed $/day values |
| `sc.cal.is.v3.usd` | −$6 | -5.9173 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of $/day |
| `sc.cal.oos.v05.c` | +0.82 | 0.8171 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of net cents/share |
| `sc.cal.oos.v05.cci` | [0.39, 1.25] | [0.3874, 1.2488] | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of the per-seed cents/share CI bounds |
| `sc.cal.oos.v05.sr` | 12.2 | 12.1576 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of the per-seed Sharpe |
| `sc.cal.oos.v05.uci` | [15, 157] | [15.4607, 156.9616] | ✓ | 02_cv_cells_seeds.sql | 2.5-97.5 % of the 20 seed $/day values |
| `sc.cal.oos.v05.usd` | +$81 | 81.3485 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of $/day |
| `sc.cal.oos.v1.c` | +0.66 | 0.6546 | ✗ | 02_cv_cells_seeds.sql | 20-seed mean of net cents/share |
| `sc.cal.oos.v1.cci` | [0.10, 1.19] | [0.0978, 1.1886] | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of the per-seed cents/share CI bounds |
| `sc.cal.oos.v1.sr` | 8.8 | 8.8495 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of the per-seed Sharpe |
| `sc.cal.oos.v1.uci` | [1, 130] | [0.6459, 129.5159] | ✓ | 02_cv_cells_seeds.sql | 2.5-97.5 % of the 20 seed $/day values |
| `sc.cal.oos.v1.usd` | +$57 | 56.5929 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of $/day |
| `sc.cal.oos.v3.c` | −1.47 | -1.4657 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of net cents/share |
| `sc.cal.oos.v3.cci` | [−4.45, 1.34] | [-4.4479, 1.3436] | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of the per-seed cents/share CI bounds |
| `sc.cal.oos.v3.sr` | −2.4 | -2.3507 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of the per-seed Sharpe |
| `sc.cal.oos.v3.uci` | [−41, 37] | [-41.0089, 36.9971] | ✓ | 02_cv_cells_seeds.sql | 2.5-97.5 % of the 20 seed $/day values |
| `sc.cal.oos.v3.usd` | −$11 | -11.384 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of $/day |
| `sc.pre.is.v05.c` | +0.61 | 0.6131 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of net cents/share |
| `sc.pre.is.v05.cci` | [0.08, 1.14] | [0.0771, 1.1383] | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of the per-seed cents/share CI bounds |
| `sc.pre.is.v05.sr` | 4.0 | 3.999 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of the per-seed Sharpe |
| `sc.pre.is.v05.uci` | [−1, 59] | [-0.9759, 59.4791] | ✓ | 02_cv_cells_seeds.sql | 2.5-97.5 % of the 20 seed $/day values |
| `sc.pre.is.v05.usd` | +$28 | 28.4291 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of $/day |
| `sc.pre.is.v1.c` | +0.40 | 0.401 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of net cents/share |
| `sc.pre.is.v1.cci` | [−0.32, 1.08] | [-0.3241, 1.0784] | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of the per-seed cents/share CI bounds |
| `sc.pre.is.v1.sr` | 2.1 | 2.1527 | ✗ | 02_cv_cells_seeds.sql | 20-seed mean of the per-seed Sharpe |
| `sc.pre.is.v1.uci` | [−9, 43] | [-8.7633, 43.1508] | ✓ | 02_cv_cells_seeds.sql | 2.5-97.5 % of the 20 seed $/day values |
| `sc.pre.is.v1.usd` | +$15 | 14.7804 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of $/day |
| `sc.pre.is.v3.c` | −1.35 | -1.3493 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of net cents/share |
| `sc.pre.is.v3.cci` | [−3.15, 0.37] | [-3.1466, 0.3668] | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of the per-seed cents/share CI bounds |
| `sc.pre.is.v3.sr` | −2.6 | -2.5944 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of the per-seed Sharpe |
| `sc.pre.is.v3.uci` | [−24, 19] | [-24.2266, 18.7767] | ✓ | 02_cv_cells_seeds.sql | 2.5-97.5 % of the 20 seed $/day values |
| `sc.pre.is.v3.usd` | −$13 | -12.6811 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of $/day |
| `sc.pre.oos.v05.c` | −0.02 | -0.0178 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of net cents/share |
| `sc.pre.oos.v05.cci` | [−1.22, 1.09] | [-1.2212, 1.0856] | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of the per-seed cents/share CI bounds |
| `sc.pre.oos.v05.sr` | 2.1 | 2.1411 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of the per-seed Sharpe |
| `sc.pre.oos.v05.uci` | [−30, 81] | [-29.721, 81.2305] | ✓ | 02_cv_cells_seeds.sql | 2.5-97.5 % of the 20 seed $/day values |
| `sc.pre.oos.v05.usd` | +$15 | 15.1644 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of $/day |
| `sc.pre.oos.v1.c` | −0.38 | -0.3826 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of net cents/share |
| `sc.pre.oos.v1.cci` | [−2.08, 1.21] | [-2.0826, 1.2047] | ✗ | 02_cv_cells_seeds.sql | 20-seed mean of the per-seed cents/share CI bounds |
| `sc.pre.oos.v1.sr` | 0.3 | 0.3444 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of the per-seed Sharpe |
| `sc.pre.oos.v1.uci` | [−36, 62] | [-36.4159, 62.4919] | ✓ | 02_cv_cells_seeds.sql | 2.5-97.5 % of the 20 seed $/day values |
| `sc.pre.oos.v1.usd` | +$4 | 4.3454 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of $/day |
| `sc.pre.oos.v3.c` | −1.69 | -1.6902 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of net cents/share |
| `sc.pre.oos.v3.cci` | [−4.85, 1.32] | [-4.8457, 1.3236] | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of the per-seed cents/share CI bounds |
| `sc.pre.oos.v3.sr` | −2.6 | -2.576 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of the per-seed Sharpe |
| `sc.pre.oos.v3.uci` | [−41, 34] | [-41.0089, 34.0356] | ✓ | 02_cv_cells_seeds.sql | 2.5-97.5 % of the 20 seed $/day values |
| `sc.pre.oos.v3.usd` | −$13 | -12.6675 | ✓ | 02_cv_cells_seeds.sql | 20-seed mean of $/day |
| `cv.cal.is.sr` | 11.9 | 11.9538 | ✗ | 03_cv_daily_sharpe.sql | per-seed Sharpe from daily P&L, mean over 20 seeds |
| `cv.cal.is.usd` | +$94 | 94.3466 | ✓ | 03_cv_daily_sharpe.sql | mean daily P&L over seeds and days |
| `cv.cal.oos.sr` | 8.8 | 8.8495 | ✓ | 03_cv_daily_sharpe.sql | per-seed Sharpe from daily P&L, mean over 20 seeds |
| `cv.cal.oos.usd` | +$57 | 56.5929 | ✓ | 03_cv_daily_sharpe.sql | mean daily P&L over seeds and days |
| `cv.pre.is.sr` | 2.1 | 2.1527 | ✗ | 03_cv_daily_sharpe.sql | per-seed Sharpe from daily P&L, mean over 20 seeds |
| `cv.pre.is.usd` | +$15 | 14.7804 | ✓ | 03_cv_daily_sharpe.sql | mean daily P&L over seeds and days |
| `cv.pre.oos.sr` | 0.3 | 0.3444 | ✓ | 03_cv_daily_sharpe.sql | per-seed Sharpe from daily P&L, mean over 20 seeds |
| `cv.pre.oos.usd` | +$4 | 4.3454 | ✓ | 03_cv_daily_sharpe.sql | mean daily P&L over seeds and days |
| `t3.is.c` | −0.22 | -0.2197 | ✓ | 04_tier0_v3_blind.sql | per-seed total P&L / total shares, mean over 20 seeds |
| `t3.oos.c` | −0.52 | -0.5169 | ✓ | 04_tier0_v3_blind.sql | per-seed total P&L / total shares, mean over 20 seeds |
| `fresh.s1.cal.v05.usd` | +$18.3 | 18.2671 | ✓ | 05_fresh_holdout.sql | mean over 20 seeds of mean daily P&L |
| `fresh.s1.cal.v1.usd` | −$1.5 | -1.4945 | ✓ | 05_fresh_holdout.sql | mean over 20 seeds of mean daily P&L |
| `fresh.s1.cal.v3.usd` | −$24.7 | -24.6661 | ✓ | 05_fresh_holdout.sql | mean over 20 seeds of mean daily P&L |
| `fresh.s1.pre.v05.usd` | −$23.5 | -23.5006 | ✓ | 05_fresh_holdout.sql | mean over 20 seeds of mean daily P&L |
| `fresh.s1.pre.v1.usd` | −$22.4 | -22.3689 | ✓ | 05_fresh_holdout.sql | mean over 20 seeds of mean daily P&L |
| `fresh.s1.pre.v3.usd` | −$25.6 | -25.6433 | ✓ | 05_fresh_holdout.sql | mean over 20 seeds of mean daily P&L |
| `fresh.s2.cal.v05.usd` | +$50.8 | 50.7568 | ✓ | 05_fresh_holdout.sql | mean over 20 seeds of mean daily P&L |
| `fresh.s2.cal.v1.usd` | +$20.2 | 20.1978 | ✓ | 05_fresh_holdout.sql | mean over 20 seeds of mean daily P&L |
| `fresh.s2.cal.v3.usd` | −$28.3 | -28.2979 | ✓ | 05_fresh_holdout.sql | mean over 20 seeds of mean daily P&L |
| `fresh.s2.pre.v05.usd` | −$20.5 | -20.4958 | ✓ | 05_fresh_holdout.sql | mean over 20 seeds of mean daily P&L |
| `fresh.s2.pre.v1.usd` | −$28.1 | -28.1406 | ✓ | 05_fresh_holdout.sql | mean over 20 seeds of mean daily P&L |
| `fresh.s2.pre.v3.usd` | −$31.4 | -31.3599 | ✓ | 05_fresh_holdout.sql | mean over 20 seeds of mean daily P&L |
| `fresh.show.cal` | +$12.4 | 12.376 | ✓ | 05_fresh_holdout.sql | showcase match, S2 at 0.5 s: total P&L over 20 seeds / 20 |
| `fresh.show.pre` | −$6.4 | -6.416 | ✓ | 05_fresh_holdout.sql | showcase match, S2 at 0.5 s: total P&L over 20 seeds / 20 |
| `capcv.half.is` | $73,000 | 73,288.5035 | ✓ | 06_capacity_seeds.sql | capital where the seed-mean Sharpe halves (log-linear) |
| `capcv.half.is.day` | $183 | 183.4463 | ✓ | 06_capacity_seeds.sql | $/day where Sharpe halves |
| `capcv.half.oos` | $40,000 | 40,245.1081 | ✓ | 06_capacity_seeds.sql | capital where the seed-mean Sharpe halves (log-linear) |
| `capcv.half.oos.day` | $68 | 67.472 | ✗ | 06_capacity_seeds.sql | $/day where Sharpe halves |
| `capcv.halfall.is` | $165,000 | 164,684.5654 | ✓ | 06_capacity_seeds.sql | capital where the seed-mean Sharpe halves (log-linear) |
| `capcv.halfall.is.day` | $517 | 517.2423 | ✓ | 06_capacity_seeds.sql | $/day where Sharpe halves |
| `capcv.halfall.oos` | $97,000 | 96,925.9674 | ✓ | 06_capacity_seeds.sql | capital where the seed-mean Sharpe halves (log-linear) |
| `capcv.halfall.oos.day` | $278 | 277.7732 | ✓ | 06_capacity_seeds.sql | $/day where Sharpe halves |
| `capcv.pmax.is` | $219,000 | 219,200.7859 | ✓ | 06_capacity_seeds.sql | capital of the highest-$/day cell |
| `capcv.pmax.is.day` | $339 | 338.9825 | ✓ | 06_capacity_seeds.sql | highest seed-mean $/day |
| `capcv.pmax.is.sr` | 2.0 | 1.9853 | ✓ | 06_capacity_seeds.sql | Sharpe of the highest-$/day cell |
| `capcv.pmax.oos` | $83,000 | 83,047.1826 | ✓ | 06_capacity_seeds.sql | capital of the highest-$/day cell |
| `capcv.pmax.oos.day` | $177 | 176.8696 | ✓ | 06_capacity_seeds.sql | highest seed-mean $/day |
| `capcv.pmax.oos.sr` | 1.3 | 1.2892 | ✓ | 06_capacity_seeds.sql | Sharpe of the highest-$/day cell |
| `capcv.pre.sr0.is` | 2.7 | 2.7243 | ✓ | 06_capacity_seeds.sql | seed-mean Sharpe at the smallest size (top-10 matches) |
| `capcv.pre.sr0.oos` | 0.8 | 0.8504 | ✗ | 06_capacity_seeds.sql | seed-mean Sharpe at the smallest size (top-10 matches) |
| `capcv.sr0.is` | 13.6 | 13.6342 | ✓ | 06_capacity_seeds.sql | seed-mean Sharpe at the smallest size (top-10 matches) |
| `capcv.sr0.oos` | 10.6 | 10.5906 | ✓ | 06_capacity_seeds.sql | seed-mean Sharpe at the smallest size (top-10 matches) |

Not re-derived here: v2's capital (3 x peak dollars locked) needs the trade ledger, which is not in git, so the percentages in `01_v2_daily.sql` divide re-derived dollars by the stored capital from `results/v2/note_metrics.json`. The fresh-holdout confidence intervals are not seed percentiles of the committed rows (see `05_fresh_holdout.sql`).
