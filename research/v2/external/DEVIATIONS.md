# X1 deviations from research/v2/external/PREREG_EXTERNAL.md

## D1 (2026-10-04, 10:26 UTC): the print build stopped on an exception; runner fixed to match the U1/U2 builders

- First invocation of `research/v2/external/x1_test.py` at 163195b: START line written to
  `results/oos_peeks.log` at 10:26:14 UTC; 108 of 108 window tapes fetched into `data/external_x1/raw/trades`;
  then the print build stopped with `IndexError` in `src/tiers.py:80` (`match_prints`) on a market whose
  in-play tape has at least 20 prints but no jump detection, so the onset array is empty.
- Nothing was evaluated. No print table was written and no P&L, markout summary or strategy statistic was
  produced or viewed. The only output was the fetch count (108 of 108) and the traceback. The build had loaded
  the window resolutions into memory; none was printed.
- Cause: the runner called `src.tiers.match_prints` directly. The U1 builder (`src/prints.py::_one`) and the U2
  builder (`research/v2/expand/build_u2.py::_one`) wrap the same call in `try/except` and drop a market whose
  build raises. The pre-registration specifies prints built with `src.tiers.match_prints(row)` as in U1/U2.
- Fix (the commit that adds this file): the runner wraps `match_prints` the same way and reports the dropped
  markets separately (`build.n_match_prints_raised`, `build.match_prints_raised`). Runner sha256 after the fix:
  00281742be351a6c9985cb4d698972ace0b551571c685935741f2ac432decc1b (pre-registered version:
  bee9664031d9ef1d3cd1f79864f1803677b99900b8f1186dc671a9e922864ff8). Nothing else changes: the universe,
  window, policy, latency inputs, metrics, verdict rule and labels are as pre-registered, and the tapes are the
  ones already fetched (cached, not re-fetched; their sha256 are recorded in the results).
- The run is restarted once at that commit. Both START lines stay in `results/oos_peeks.log`; the restart is
  the single evaluation, not a reproduction, because the first invocation evaluated nothing.
