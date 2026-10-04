# Clean-clone test (judge path), 2026-10-03

## Final judge path (2026-10-04; this is what README, `docs/DEVPOST.md` and `bash run.sh help` say)

Times are the measured ones below (Linux clean clone / the authors' Mac); every command runs from the repo root.

| path | commands | time | tested on a clean clone |
|---|---|---|---|
| **Read and watch** | `docs/NOTE.pdf` (5 main pages), `results/viz/courtside_60.mp4` (90 s) | ~10 min | n/a |
| **Quick path** (no data download, no keys) | `bash run.sh setup` | 34-45 s | yes (F1, F2 fixed) |
| | `bash run.sh replay` | 5-7 s Linux, ~15 s Mac | yes |
| | `bash run.sh redteam` (re-derives every Q&A number, greps the public text) | ~10 s | authors' Mac |
| | `bash run.sh tests` | 110-123 s Linux; 393 s on a loaded laptop | yes (90 passed, 1 skipped on GitHub `597b0de`) |
| | `bash run.sh docs` (README, Devpost text, compliance checklist from `results/paper/numbers.json`) | < 1 s | authors' Mac |
| **One-command reproduction** | `bash run.sh all` = `setup` → `data` (public crawl, resumable, no keys) → `reproduce` (`reproduce.sh`: results, figures, `results/paper/numbers.json`, `docs/NOTE.pdf`, the docs) | ~1.5-2.5 h (crawl ~1-2 h; `reproduce.sh` ~15-20 min) | **no**: the crawl and the full `reproduce.sh` were last run end to end on the authors' machine (see "Not tested") |

Changes in the final pass: `reproduce.sh` now runs `scripts/build_paper.py` with figures on (it had `--no-figures`, so
the paper's own figures in `results/paper/v2/` were not redrawn) and ends with `scripts/build_docs.py`; `run.sh` gained
`all` and `docs`; `run.sh preflight` no longer expects the live paper session (stopped by a team decision,
`research/v2/maker/DEVIATIONS_LIVE.md` L15) and checks that the docs match `numbers.json`. The blind forward test
(`HYPOTHESIS_V2.md` A4) has one slot in the paper, README and Devpost text; it fills from `results/v2/forward.json`
when `scripts/build_paper.py` and `bash run.sh docs` are re-run after the 11:30 UTC run.

## Original test (2026-10-03)

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
| `bash run.sh help` | **FAIL** (F1); ok on the later push `8e3c92f` | - |
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

**F1. GitHub did not have the judge path at test time (blocker then; partly resolved).** On `3d46204`,
`bash run.sh help` -> `bash: run.sh: No such file or directory`: `run.sh`, `tests/fixtures/live_sample.jsonl.gz`,
`scripts/replay_sample.py` and `scripts/live_paper.py` existed only in local commits. Another workflow then pushed
`8e3c92f`, which contains `2a8c5e4`. Recheck on a fresh clone of `8e3c92f` (20:45 UTC,
`/blue/ai-workshop/ojasvamishra/cleanclone_20261003_204533`): setup ok (45 s), `run.sh help` ok,
`run.sh replay --no-dashboard` ok (7 s, same output), but `run.sh tests` still fails with F2 because the fixes in
this commit are not pushed yet. **Push again before judging.**

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

## Update after FINAL_PREP_REVIEW (2026-10-03, ~21:35 UTC)

Re-run on a fresh clone of GitHub `597b0de` (see `FINAL_PREP_REVIEW.md`, "Clean-clone re-runs"): F1 and F2 are
resolved on GitHub (`run.sh help` exit 0; `run.sh tests` on a core install: 90 passed, 1 skipped, 393 s on the
loaded laptop). The "push again" note under F1 is out of date. F6 and F8d were still open on `597b0de`.

Fixed in files this workflow owns (`run.sh`, README judge box, deck, video):

- **F6** `run.sh money` now checks for `data/v2_trades_is_oos.parquet` and prints the order to run things
  (`data`, then `reproduce`, then `money`) instead of a `FileNotFoundError` traceback. Exit 1.
- **F5** `run.sh reproduce` now refuses to start without the event list and at least 1,000 cached tapes, and
  says to run `bash run.sh data` first (`FORCE=1` overrides). This replaces the misleading
  `AttributeError: ... 'net30_c'` on a one-day cache.
- **F7** `run.sh help` now says that `--minutes N` counts from the start of quoting, not from launch.
- **F8d** `run.sh cv`, `run.sh help` and the README judge box say the frozen call model is not in git, that
  `run.sh cv` then runs with calls disabled, and that `sbatch hpg/engine_vision.sbatch` rebuilds it. The deck
  (slide 10) and the video (closing card) say the same.
- The README judge box and the deck/video closing cards no longer claim one command reproduces everything; they
  give `bash run.sh replay` (seconds) and `bash run.sh data && bash run.sh reproduce` (~1–2 h + ~15 min).

## Needs owner

Failures or claims that trace to files this workflow may not edit. Each item gives the exact fix.

| # | file (owner) | failure on a clean clone or in the talk | exact fix |
|---|---|---|---|
| N1 | `src/polymarket.py:25-36` `_get` (research) | **F3**: the Gamma event crawl gives up after 5 tries in ~22 s (`RuntimeError: GET failed ... tag_slug=table-tennis`); `run.sh data` now retries the whole fetch 4 × 60 s as a workaround | Use exponential back-off with a longer budget: `tries: int = 8` and `time.sleep(min(60, 2 ** k))` in both the 429/5xx branch and the `RequestException` branch |
| N2 (done: `run_all.py:101`) | `run_all.py:98-102` (research) | **F5**: on too little data `fasttier.walk_forward` returns an empty frame and line 102 raises `AttributeError: 'DataFrame' object has no attribute 'net30_c'` | Right after `wf, sh, by_bucket = fasttier.walk_forward(p_is)`: `if wf.empty or "net30_c" not in wf: sys.exit("walk-forward fast tier: not enough in-sample data; run 'bash run.sh data' (full crawl) first")` |
| N3 (done: `scripts/money_counter.py:43`) | `scripts/money_counter.py` (research) | **F6** when called directly (not via `run.sh`): `FileNotFoundError: data/v2_trades_is_oos.parquet` | At start: `if not Path("data/v2_trades_is_oos.parquet").exists(): sys.exit("needs bash run.sh data, then bash run.sh reproduce (writes data/v2_trades_is_oos.parquet)")` |
| N4 | `scripts/live_paper.py` (live paper workflow) | **F7**: `--minutes 2` never exits on a quiet tape, because the clock starts only when quoting starts | Add `--max-wall-minutes M` (default: `--minutes` + 30) that stops the process M minutes after launch, warm-up included, and writes the summary with `status: "stopped: wall-clock limit (warm-up not passed)"` |
| N5 | `scripts/live_paper.py:1333` (live paper workflow) | During warm-up `summary.json` has `"now": "1970-01-01T00:00:00.000Z"` (`iso(eng.key)` with `eng.key == 0`) and `counters: {}`; an unguarded rebuild printed "as of 1970-01-01" on deck slide 8 | `"now": iso(eng.key) if eng.key else iso(int(time.time() * 1000))`, plus `"venue_clock_started": bool(eng.key)`. The deck and video now guard this (show "warming up" and the file time), so this is a correctness fix, not a blocker |
| N6 | `models/vision/frozen_call_model.pkl` + `scripts/get_models.sh` (vision workflow) | **F8d**: CV calls cannot be reproduced from a clone; the model is 12 MB and is not distributed | Publish it as a GitHub release asset (`gh release create vision-v1 models/vision/frozen_call_model.pkl --notes "frozen point-end call model, built by hpg/engine_vision.sbatch"`), then in `get_models.sh`: `[ -f models/vision/frozen_call_model.pkl ] \|\| gh release download vision-v1 -p frozen_call_model.pkl -D models/vision` (or curl the release URL). Do not commit `models/` |
| N7 | `engine/run.py:290` (engine workflow) | **F9**: `engine --mode live-market` (also run by `run.sh engine`) overwrites the tracked `results/engine/live_market_run.json`, so a judge's clone shows a dirty tree | Write to `results/engine/live_market_run.json` only with `--out`; default to `/tmp/courtside_live_market_run.json` (or a timestamped file under `results/engine/runs/`, gitignored) |
| N8 (superseded: the live session was stopped by a team decision, L15, and no live-session number is shown in the paper, video, README or Devpost) | `results/live/summary.json`, `results/live/session_*`, `results/live/STOPPED_*` (live paper workflow) | The video (S10) and the deck (slides 8, 10) read the live summary, but it is untracked, so GitHub cannot show it. (`results/tier0_v3/blind.json` and `results/spin/tennis/metrics_v2.csv` were committed by their owners during this pass, in `11d1016` and `62a5b07`.) The video manifest lists untracked sources under `source_files_not_in_git_at_render` | Commit the session files when the session ends (never `data/`), push, then rebuild the deck and re-render the video together |
| N9 | `results/engine/demo_run.json` (engine workflow, committed in `1ccf1c9`) | The re-run on the loaded laptop raised the vision processing latency from 100 ms to 158 ms (p90 219 ms); the deck (slides 2, 4) and the video (S02) now show 158 ms, labelled as a laptop benchmark with no courtside camera | If a GPU or unloaded run is the intended figure, commit it to the same key (`latency_budget[vision…].ms`) and rebuild the deck and video together; no change is needed in the deck or video code |
| N10 (done: `docs/NOTE.md` is regenerated by `scripts/build_paper.py` with the count at build time) | `docs/NOTE.md:155` (note owner) | Quotes the peek log as "19 lines"; the log had 65 lines at this build. The deck build prints a warning | Replace "19 lines" with "every look is logged; the count at build time is in the deck and video manifests" (or the count at the final note build) |
| N11 | `scripts/pm_compute.py` / `results/financials/pm_compute.json` p07 (PM review) | The note's wallet-clustered CI does not reproduce to 2 dp; the deck quotes pm_compute's value and warns | Re-run `pm_compute.py` against the note's input set, or correct the note's CI to pm_compute's value |
| N12 (done: README is generated from `docs/templates/README.md.in`; "Reproduce" uses `run.sh`, says Python 3.12+ and points to the frozen model note) | `README.md` body, "Reproduce" section (README owner; this workflow edits only the judge box) | Says `# Python 3.14` and runs `fetch_polymarket.py` + `bash reproduce.sh` directly, while the judge box (tested) uses `run.sh`; the table row "Ball tracking ... 11 of 11 calls correct" omits that the vision calls need the undistributed model | Point the section at `bash run.sh setup / data / reproduce`, say "Python 3.12+", and add "CV calls need `models/vision/frozen_call_model.pkl` (see judge box)" |
| N13 | GitHub (repo owner) | `origin/main` is at `62a5b07`; local `main` is ahead (the deck, video, run.sh and judge-box fixes of this pass are local commits), so they are not public yet | After N8, `git push origin main`; confirm with `git ls-remote origin refs/heads/main` |
