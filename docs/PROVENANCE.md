# Provenance: the experiment registry

`results/provenance/experiments.json` records, in time order, every read of out-of-sample (OOS) or
held-out data in this project, every decision taken after such a read, every pre-registration and
every reproduction. Each entry points to a git commit, to lines of the read logs and to committed
evidence. `scripts/provenance.py` validates the file and derives its summary. The paper's
statements about how the test was kept fair, and every result label it prints, should come from
this file.

```
python scripts/provenance.py check     # validate; exit 1 on any error
python scripts/provenance.py build     # recompute the derived fields, write them, then validate
python scripts/provenance.py summary   # print the derived summary
pytest tests/test_provenance.py
```

`check` needs the full git history (it resolves every commit). It reads no data and no results.

## Sources it is checked against

- `results/oos_peeks.log`: one line per OOS read, appended by the code that read it (111 lines before the 2026-10-04 repair).
  Every line must belong to exactly one event. The log is never edited; its timestamps are
  normalised to UTC in the registry (`log_lines`), whatever offset a line carries.
- `results/tracking/test_peeks.log` (tracking test set) and `results/tt/peeks.log` (table tennis):
  the same rule, through `aux_log_lines`.
- `git log`: commit existence, ancestry and committer times.
- `DEVIATIONS.md`, `HYPOTHESIS*.md` and the `PREREG*.md` / `DEVIATIONS*.md` files under `research/`.

## Events

| field | meaning |
|---|---|
| `id` | `E00`..`E59`, plus a letter for a split event (`E36b`) |
| `utc`, `utc_end` | start of the event and, if it spans several lines, its last line (UTC, to the second) |
| `time_source` | `log` (earliest own log line), `commit`, `mtime` (local file times), `document`; free text may follow |
| `commit` | commit that records the event (its results, decision text or log line); `commit_role: "code"` when it is instead the code that ran, committed before the event |
| `subject_commit` | code under test, when it differs from `commit` (reproductions and verifiers) |
| `prereg_commit` | commit that froze the rule; required for kinds `a` and `f`; must precede the read unless `prereg_commit_after_run: true` discloses otherwise |
| `kind` | see below |
| `decision` | true exactly for kinds `d` and `e` |
| `family` | `v1`, `v2`, `tracking`, `forward`, `cv`, `maker`, `capacity`, `tt`, `replay` |
| `data_state` | `clean`, `burned` (machine code for the U1 OOS after its first read; never printed), `untouched`, `partly_read`, `forward`, `test_used` |
| `direction` | required for kinds `d` and `e`: effect on the reported number |
| `oos_selected` | a `d`/`e` event that picked the reported variant after seeing its OOS value |
| `printed_text` | required for kinds `d` and `e`: at most 25 neutral words, printed verbatim by the paper; never "burned" |
| `oos_log_lines`, `aux_log_lines`, `logged_after_lines` | log lines this event wrote; lines known to be written after the read |
| `evidence` | at least one verifiable item: a tracked path (optionally `:a-b` line range), `git:<rev>:<path>` or `commit:<rev>`; `local:<path>` marks an untracked file on the authors' machine and never counts as support |
| `touches` | result ids this event produced or shaped |
| `oos_informed` | derived: kind `d` or `e` after a look at OOS or held-out data (not forward recordings) |

Kinds:

| code | printed kind |
|---|---|
| `a` | pre-registered evaluation |
| `b` | reproduction (no decision, no new statistic) |
| `c` | replay-diagnostic (sensitivity, diagnostic or descriptive read; may add statistics; chooses nothing) |
| `d` | design/headline choice after an OOS look |
| `e` | defect fix after an OOS look (with direction) |
| `f` | blind or post-freeze evaluation |
| `protocol` | protocol change that read no data |

## Results

Each result has `period`, `kind` (`executable`, `sim_upper_bound`, `others_fills`, `conditional`,
`event_study`, `descriptive`, `diagnostic`), `label`, `label_text` (the printed row label),
`flags`, `events` and `paper_keys` (globs over `results/paper/numbers.json` keys).

`events` must equal the set of events whose `touches` name the result. The `label` is derived, in
this order, by `derive_label`:

1. `in-sample`: the period is IS.
2. `not-run`: no event read data.
3. `blind`: a kind `f` event exists, every `f` event read `untouched` data and was pre-registered
   before the read. Otherwise `post-freeze`.
4. `clean-oos`: a kind `a` event read clean data and no `d`/`e` event touches the result.
5. `burned-non-blind` (printed "non-blind"): an OOS-informed `d`/`e` event touches the result, or
   an event read burned or test_used data.
6. `exploratory`: everything else.

Required flags are checked: `oos_selected`, `oos_informed_design`, `defect_fix_after_oos`,
`prereg_committed_after_run`.

## Derived fields (never edit by hand)

`events[].oos_informed`, `log_lines` and `summary` are written by `build`; `check` fails if they
differ from a recomputation. `summary` holds the counts by kind, the list of OOS-informed decisions
with their `printed_text`, defect fixes with direction, pre-registered and blind or post-freeze
evaluations, reproductions, diagnostics, unlogged reads, the log-line totals (with
`log_lines_unmapped` = 0) and the results grouped by label. A log-line count is not a count of
"reads": lines include reproductions, verifiers, re-runs and cluster copies of one job.

## `test_eligibility`

A metadata-only answer to whether an untouched test that meets the organizer rule (latest 20% of
history or latest two years, whichever is shorter, evaluated once) exists inside the declared
universe. It was written from catalogue counts, dates, the read logs and commits, without reading
any candidate test profit. Current answer: no. The qualifying window (U1 matches from 2026-08-25
14:15 UTC) was evaluated once, cleanly, by v1 (E02), and every newer candidate is either outside
the universe or far shorter than the rule requires.

## Adding events (recompute and later work)

1. Run the read through the logging helper so that it appends its line to `results/oos_peeks.log`
   (reproduction mode writes elsewhere and adds no line).
2. Append an event: kind `b` for a re-run of an already-reported number under corrected code, kind
   `e` for a defect fix after an OOS look (with `direction` and `printed_text`), kind `f` only for
   data first read after a freeze commit. A re-run on the old OOS period is never `f` or blind.
   If the commit that records the run is the same one that adds the event, set `commit` to the
   code commit and `commit_role: "code"`.
3. Add the event id to the `touches` of the results it changes, and add new results with their
   `period`, `kind`, `label_text` and `paper_keys`.
4. `python scripts/provenance.py build && python scripts/provenance.py check`, then commit the
   registry with the results.

## Corrections made to the 2026-10-04 draft registry

The draft (59 events) was checked event by event against git, the read logs and the deviation files.

- **E10:** the in-sample ranking of the seven causal variants is T3g, T3h, T3b, T3d, T3e, T3c, T3f.
  T3e ranks fifth, not first. T3h is a full causal relabel, like T3e and T3f, and ranks above T3e
  in sample. T3e is the only variant whose OOS CI excludes 0.
- **E08:** times come from output mtimes, 13:35:01 to 13:48:38 UTC. The evidence is now the
  committed `rebuild_report.json` and `leakage_check.json`; the untracked `.log` is marked `local:`.
- **E29:** the clean-clone run did not finish `run_all.py --oos`, so it reproduces the v2 outputs
  but not H1-H6 or v1. The recording commit is 50f0a64.
- **E39:** U2 had been read by the v2 and v2-safe tests before tier-0 v3 was frozen. The v3 U2
  result is relabelled `post-freeze` (it was `blind`).
- **E41:** 3.14 s predates any P&L: it is a grid level in the tier-0 PREREG, from the live-day
  calibration. The choice made after the OOS cells was to make that reading the post hoc headline.
- **E45:** the earliest evidence of the 1 s base case is e1b5272 (21:27:27 UTC), not 913f5da.
- **E53, E59:** reclassified from reproduction to diagnostic, because they add new statistics.
  E36 is split into E36 (reproduction) and E36b (selection check and fee stress).
- **E21:** the draft's directions (V2 up, V4 down) are not supported by the one-change stresses in
  the tier-0 RESULTS.md (a5769c7). Those stresses show V1 and V5 lowered P&L and V2, V4 and V6 changed
  it little. The per-fix directions are in `sub_directions`.
- **E28:** the 0-quote, 0-fill statement covers the first live session only. The restarted session was
  stopped by team decision, and none of its output is used as evidence.
- **E05:** moved to its own result, `R_tracking_relabel`. The paper's 11/11 (`R_tracking_test`)
  is the clean pre-specified evaluation.
- Added `R_v2_copier` (the executable copier stress, E52). Added the table-tennis log mapping and
  the tracking test-log mapping.
- Times and commits were aligned to the git record: E06, E13, E14, E21 and E42; E57 and E58 now name
  the commit that recorded them (51dff68) with the code under test as `subject_commit`; E47's log line
  is marked as written after the read.
