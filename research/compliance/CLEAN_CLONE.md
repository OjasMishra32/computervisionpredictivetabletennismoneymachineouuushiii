# Clean-clone test (judge path), 2026-10-03

Two fresh trees on HiPerGator compute nodes (Linux x86_64, `module load python/3.12` = Python 3.12.5,
`ffmpeg/n6.1`), each with a new venv and nothing from our `data/`, `models/` or pip caches of the project:

| tree | what | dir on HiPerGator |
|---|---|---|
| **GitHub** | `git clone https://github.com/OjasMishra32/computervisionpredictivetabletennismoneymachineouuushiii`, i.e. what judges see. HEAD `3d46204` | `/blue/ai-workshop/ojasvamishra/cleanclone_20261003_200526` |
| **Local** | `git clone` of the local repo at `d007946` (then 11 commits ahead of GitHub, including the `run.sh` commit `2a8c5e4`), rsynced over; later rounds rsynced the fixed `run.sh` and `requirements-extra.txt` | `/blue/ai-workshop/ojasvamishra/cleanclone_20261003_200526_local` |

Logs are in `<dir>.logs/` (round 1, 20:06-20:24 UTC), `<dir>_local.logs2/`, `.logs3/`, `.logs4/` (reruns
after each fix, to 20:45 UTC). Each `steps.tsv` lists step, exit code, seconds and the exact command.
The only market data fetched was the public event list and the trade tapes of in-sample days (2025-11-15,
2026-01-15). The locked out-of-sample period starts 2026-08-25, so no out-of-sample or forward-window tape
was downloaded or read. As on any fresh clone, `run_all.py --oos` and `live_paper.py --replay` appended a line
to that clone's own `results/oos_peeks.log`. Those clones are throwaway and nothing from them is committed.

## Results

GitHub tree (pushed state):

| command | result | time |
|---|---|---|
| `git clone`, `python3 -m venv .venv`, `pip install -r requirements.txt` | ok on Python 3.12.5 (README says 3.14) | 3 s + 32 s |
| `bash run.sh help` | **FAIL** (F1) | - |
| `pytest tests engine/vision/tests` | **FAIL**, collection error (F2) | 2 s |
| `pytest tests` (the README's command) | 70 passed, 1 skipped | 161 s |
| `python -m engine.run --mode backtest` | ok (prints the stored tier-0 counterfactual, labelled as such) | 1 s |
| `python -m engine.run --mode live-market --seconds 30` | ok, live public books, read-only, no orders | 36 s |

Local tree (committed `run.sh`, then the fixes listed under each failure):

| command | result | time |
|---|---|---|
| `bash run.sh setup` (venv + `requirements.txt`) | ok | 34 s |
| `bash run.sh tests`, core install | round 1 **FAIL** (F2); after the fix 85 passed, 1 skipped (vision tests skipped with a message) | 110 s |
| `pip install -r requirements-extra.txt` (= `setup --full`) | ok (torch 2.14.1, onnxruntime 1.30.0) | 93 s |
| `bash run.sh tests`, full install | 93 passed, 2 skipped | 119-123 s |
| `bash run.sh replay --no-dashboard` | ok; same fills and paper P&L per book as the macOS run; engine books: 140,801 messages, 0 of 732 snapshot checks mismatched | 5 s |
| `bash run.sh engine books` | ok | 1 s |
| `bash run.sh engine` | ok: demo inputs absent, so it showed the sample books, then 30 s of live books (F9) | 38 s |
| `bash run.sh live --minutes 2 --no-dashboard` | connected and read the live feed; **did not exit** within 400 s (F7) | 400 s (timeout) |
| `bash run.sh dashboard 8799` | ok: `index.html` and `control.html` served (HTTP 200) | 8 s |
| `bash run.sh data --smoke` (2026-01-15) | ok: 38 in-sample matches, 38 tapes (event list already cached; cold ~30 s more) | 6 s |
| event list for the full crawl | tennis ok (39,340 events, ~25 s); table-tennis **FAIL** (F3) | 28 s |
| `bash run.sh reproduce` on one day of tapes | **partial** (F5) | 24-34 s |
| `bash run.sh money` | **FAIL** (F6) | 1 s |
| `bash run.sh cv --max-frames 300` (`CV_BACKEND=onnx-cpu`) | round 1-3 **FAIL** (F8); after the fixes ok: weights fetched and exported to ONNX, clip cut, 300 frames detected and tracked at 2.7 fps on 4 CPUs; **no calls** (F8d) | 255 s |
| `scripts/make_pdf.py` | ok: no Chrome on the node, so it wrote `docs/NOTE.html` and kept the committed PDF | 0 s |

## Failures, exact errors, and what was done

**F1. GitHub does not have the judge path (blocker).** `bash run.sh help` -> `bash: run.sh: No such file or
directory`. `run.sh`, `tests/fixtures/live_sample.jsonl.gz`, `scripts/replay_sample.py` and `scripts/live_paper.py`
exist only in local commits: `origin/main` is `3d46204`, local `main` is ahead by 11+ commits. Not fixed here
(this workflow does not push). **Push before judging**, then re-run this test on the pushed state.

**F2. `pytest tests engine/vision/tests` fails on a core install.**
`ModuleNotFoundError: No module named 'cv2'` (`src/tracking/detect.py:24`, imported by
`engine/vision/stream.py:84` from `engine/vision/tests/test_stream.py:15`); pytest stops at collection
("Interrupted: 1 error during collection"). Fixed in `run.sh tests`: the vision tests run only when opencv and
scikit-learn are installed (`setup --full`), otherwise it says so and runs `tests/`.

**F3. Polymarket's Gamma API rate-limits the event crawl.**
`RuntimeError: GET failed: https://gamma-api.polymarket.com/events {'tag_slug': 'table-tennis', 'closed': 'true',
'limit': 100, 'offset': 0, 'start_date_min': '2025-08-25', 'start_date_max': '2025-08-26'}`
(`src/polymarket.py:36`), right after the tennis list. The same URL returned HTTP 200 minutes later: 5 tries over
~22 s is too short a back-off. `scripts/fetch_polymarket.py` crashes there and the table-tennis list is not cached
until it completes. Fixed in `run.sh data`: up to 4 attempts 60 s apart; every finished read stays cached, so each
attempt resumes. Not fixed: the retry budget in `src/polymarket.py` (read-only for this workflow).

**F4. The first smoke-test definition was too thin.** Events *created* on 2025-11-15 gave 1 moneyline.
`run.sh data --smoke DAY` now fetches the full event list (as the crawl does) and the tapes of the singles that
*start* on DAY; default 2026-01-15 (38 in-sample matches).

**F5. `reproduce.sh` cannot run on one day of tapes (expected; full run not tested).**
- `run_all.py --oos`: `AttributeError: 'DataFrame' object has no attribute 'net30_c'` (`run_all.py:102`, after
  "IS strategies done"): the walk-forward fast-tier table is empty with one day. The error does not say
  "not enough data".
- `scripts/v2_causal.py`: `FileNotFoundError: [Errno 2] No such file or directory: 'data/locked/oos_prints.parquet'`
  (written by `run_all.py --oos`).
- `scripts/v2_cost_stress.py`, `scripts/v2_figures.py`, `scripts/factor_regression.py`:
  `FileNotFoundError: [Errno 2] No such file or directory: 'data/v2_trades_is_oos.parquet'` (written by
  `v2_causal.py`).
- Ran: `scripts/note_metrics.py` (event list + committed results), `scripts/leverage_stats.py` (simulation,
  283 s), `scripts/make_pdf.py`.
The chain needs the full crawl (`bash run.sh data`, ~1-2 h). Not done here.

**F6. `run.sh money` needs `reproduce`, not just `data`.**
`FileNotFoundError: [Errno 2] No such file or directory: 'data/v2_trades_is_oos.parquet'`
(`scripts/money_counter.py`; the file is written by `scripts/v2_causal.py`). `run.sh help` now says so.

**F7. `run.sh live --minutes 2` does not stop after 2 minutes on a quiet tape.** The live paper trader waits
for 50 public trades (the pre-registered trade-side check) before quoting, and `--minutes` counts from the
start of quoting. At 20:07-20:14 UTC only 2 trades arrived, so it was still warming up when the 400 s test
timeout killed it (exit 124). The feed itself was connected (90 messages). Not a crash. `run.sh help` now
explains the warm-up. `scripts/live_paper.py` is unchanged (read-only for this workflow).

**F8. `run.sh cv` from a clean clone.**
- (a) `ModuleNotFoundError: No module named 'omegaconf'` (`engine/vision/export_onnx.py:28`, called by
  `scripts/get_models.sh`). `requirements-extra.txt` also lacked `onnx` and `onnxruntime`. Fixed: added
  `onnx==1.23.1`, `onnxruntime==1.30.0`, `omegaconf==2.3.1` (versions from our venv).
- (b) HiPerGator's ffmpeg has no TLS: `Error opening input: Protocol not found` /
  `Error opening input file https://lab.osai.ai/datasets/openttgames/data/test_2.mp4.` Fixed: if ffmpeg lacks
  https, `run.sh` downloads `test_2.mp4` (225 MB) with curl first, then cuts the same 1000 frames.
- (c) `ValueError: need at least one array to stack` (`src/tracking/common.py:46`, `table_mask`): the table
  masks come from the OpenTTGames markup, which is not in git, and `src/tracking/common.py` defaults to the
  authors' HiPerGator path. Fixed: `run.sh cv` fetches `test_2.zip` (0.9 MB markup) into
  `data/openttgames/markup/test_2` and sets `OTTG_ROOT`.
- (d) **Not fixed: no calls from a clone.** `models/vision/frozen_call_model.pkl` (the frozen point-end
  classifier, built on HiPerGator by `hpg/engine_vision.sbatch`) is not distributed, so the clean-clone run
  detects and tracks but prints "calls disabled". A judge cannot reproduce the CV calls without that file
  or the training run. CPU-only ONNX ran at 2.7 fps on 4 cores, far below the clip's 120 fps; realtime use
  needs a GPU or CoreML backend.

**F9. `engine demo` cannot run from a clone.** It needs `data/live/market_*` (our live recordings),
`data/vision/test_2_copyts.mp4` and `models/vision/`, none of which are in git. `run.sh engine` detects this and
shows the engine's books on the committed sample, then live books. Side effect: `engine --mode live-market`
rewrites the tracked `results/engine/live_market_run.json`.

**Not failures, for the record.** The dashboard step's exit code 143 came from the test harness (`pkill -f`
matched its own shell). Both pages returned HTTP 200. Every replay appends one line to `results/oos_peeks.log`,
by design of `scripts/live_paper.py`.

## Not tested

- The full crawl (`bash run.sh data`, ~1-2 h, ~13k tapes) and a full `bash run.sh reproduce` on it. On the
  authors' laptop `reproduce.sh` last ran end to end in ~15 min after the crawl (`reproduce.log`).
- `bash run.sh setup` on macOS from scratch. The other commands above were also run on the authors' Mac
  (Python 3.14): `run.sh replay` (same output as Linux) and the full pytest suite (96 passed, 2 skipped, 6 min
  on a loaded laptop, working tree).
