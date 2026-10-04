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
| `id` | `E00`..`E64`, plus a letter for a split event (`E36b`) |
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
| `decision_class` | what the change actually was (see "Decision classes"); `3` for kinds `a`, `b`, `c`, `f`; absent on `protocol` |
| `class_evidence` | required for kinds `d` and `e`: the actual code or configuration change and its contemporaneous evidence |
| `sub_classes` | for `decision_class: "mixed"` (E21): a class per entry of `sub_decisions` |
| `presentation_choice` | a class-3 headline or scenario choice made after OOS cells existed; it changes no trade |
| `pre_change_reference` | required for class 1: the result before the change |

`oos_informed` is the registry's chronological flag for a design choice or defect correction after
a held-out look. It does not by itself establish that performance drove a change. The separate
kind, evidence and `oos_selected` fields determine what happened. A reproduction, download or
metadata inspection alone is not a finding of tuning.

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

## Decision classes

Each `d`/`e` event is classified from the code or configuration change it made and the evidence written at the
time, following the verified decision trace of 2026-10-04 (the reviewer's corrections prevail over the first
draft):

| class | meaning | events |
|---|---|---|
| `1` | new policy, parameter or variant chosen with knowledge of its evaluation performance | E06 (v2), E50 (per-wallet cap), E44 (selective replay; exploratory, on the calibration matches, not held-out data) |
| `2` | mechanical correction of the implementation to a rule written before the change | E14 (T1), E21 V6, E60 (strict timing), E61 (causal CV trade set) |
| `3` | no strategy decision: evaluation, reproduction, diagnostic, or a model, accounting or presentation change | every `a`/`b`/`c`/`f` event; E05, E11, E12, E21 V1/V2/V4, E23, E43; presentation choices E22, E41, E45, E64 |
| `4` | unsupported: real change after an OOS look, but no evidence that held-out results drove it | E16 (v2-safe), E21 V5 (limit order) |
| `undetermined` | chronology recorded, motive not: neither class 1 nor class 2 can be shown | E10 (causal window T3e) |

`oos_selected` stays a chronological record (E10, E22, E41, E45, E64). A class changes no label: everything
evaluated on the August 25 to October 3 window stays non-blind, a mechanical correction is not a clean
pre-registration, and the U2 tests of v2 and v2-safe stay blind because their pre-registration and freezes
preceded the first U2 read. `summary` lists the classes (`decision_units_by_class`,
`new_policies_after_performance` with the results each touches, `mechanical_corrections`,
`undetermined_decisions`, `unsupported_oos_allegations`, `presentation_choices_after_oos`); E21's
sub-decisions count as separate units.

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
any candidate test profit. No qualifying untouched window inside U1 has been identified. The stored
match-count split starts August 25 and lasts 38.705 days (10.745% of calendar history). The organizer
uses calendar time: July 23 06:08 UTC to October 3 07:10 UTC, 72.043 days and 4,386 matches. E02
records the first pre-registered evaluation on the stored split; it does not establish compliance
with the longer calendar-time window. External-validation feasibility is assessed separately.

## Adding events (recompute and later work)

1. Run the read through the logging helper so that it appends its line to `results/oos_peeks.log`
   (reproduction mode writes elsewhere and adds no line).
2. Append an event: kind `b` for a re-run of an already-reported number under corrected code, kind
   `e` for a defect fix after an OOS look (with `direction` and `printed_text`), kind `f` only for
   data first read after a freeze commit. A re-run on the old OOS period is never `f` or blind.
   If the commit that records the run is the same one that adds the event, set `commit` to the
   code commit and `commit_role: "code"`. Set `decision_class` (`3` for every read or re-run) and, for
   kinds `d` and `e`, `class_evidence` from the actual change and the evidence written at the time.
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
