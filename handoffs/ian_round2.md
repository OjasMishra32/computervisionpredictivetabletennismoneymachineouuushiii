# Ian: help finish the paper (updated Sun Oct 4, ~2:50 AM; hard stop 8:30 AM EDT)

What is judged: the 5-page quant note (PDF) plus a public repo that judges can run. Judges spot-check that the
note's numbers match what the code produces. If they don't, or if judges find look-ahead or tuning on held-out
data, the Performance score is capped at 4/10. Your Snowflake check already re-derives 62 of the paper's numbers.
Now we want **every** number checked.

**Stop merging PRs into main.** Main gets rewritten and force-pushed this morning. Push only your own branches,
or just send results to Ojasva.

Get the latest code from the temporary branch `snapshot-0300` (the full repo as of 3 AM; deleted after the final
push). Ojasva sends you the current PDF. To get a working copy:
```bash
git clone --branch snapshot-0300 --single-branch https://github.com/OjasMishra32/computervisionpredictivetabletennismoneymachineouuushiii ian_check && cd ian_check
```

## 1. Independent check of every number in the paper (main job, about 1.5–2 h)
`results/paper/numbers.json` lists every number printed in the paper (766). Each entry gives the printed `text` and
a `source` (`file::key`; some sources are CSV/JSON paths with filters).
- Write one script, `sponsors/snowflake/check_all.py`, extending your existing checker. It should resolve **every**
  source, read the raw value from the result file, format it the way the paper prints it, and compare it with
  `text`.
- Load the results into DuckDB as you did for Snowflake. Recompute from rows where rows exist: e.g. daily P&L CSVs
  → Sharpe and $/day, trade ledgers → per-share cents, `per_match_loss.json` → worst match.
- Output `sponsors/snowflake/out/check_all.md` with a summary line:
  `N checked: X match, Y lookup-only, Z mismatched, W unresolvable`.
  Then list every mismatch (key, printed, recomputed, source) and every source you couldn't resolve.
- Also pull the text out of the PDF's pages 1–5 (pymupdf) and flag any number printed there that isn't in
  `numbers.json` at all. A hard-coded number is a red flag for judges.
- **Send Ojasva the mismatch list as soon as you have a first pass**, ideally by 4:30 AM. Revision rounds are
  running, and early fixes land in the paper.
- Push on branch `sponsor/snowflake-final`, folder `sponsors/snowflake/` only.
- If the paper's numbers change after the final push, Ojasva tells you. Re-run then, reading
  `results/note_numbers.json` first and falling back to `results/paper/numbers.json`.

## 2. Read the paper as a judge, for three criteria (about 30 minutes, any time before 4:30 AM)
Read pages 1–5 of the PDF with the organizers' track page open
(https://www.gqhacks.com/tracks/systematic-trading: rubric, "what judges want", risk & capacity chapter).
Yoan covers Performance, Innovation and overall clarity. **You cover:**
- **Economic Foundation.** Is it clear who is on the other side of our trades, why the edge exists, and why it
  persists or what kills it? Was it written before results?
- **Risk Management.** Limits, the most we can lose on one position, de-risking rules set in advance, factor
  exposure, tail and regime risk. Is each one there, concrete and believable?
- **Liquidity & Capital.** Size as a share of volume, capacity in dollars, price impact, costs doubled. Can a judge
  find each one in under a minute?

Send short bullets: page, sentence, what's missing or weak, and the fix if you see one. Be blunt.

## 3. Quick-path run on a different machine from Yoan's (about 15 minutes)
In your clone, run `bash run.sh setup && bash run.sh redteam && bash run.sh tests`. Note your OS and Python version,
and send any error with its full output. Yoan runs the full 2-hour chain; you only check that the quick path works
on a second OS or Python version.

## 4. Optional, only if 1–3 are done: Solana pre-registration anchoring
Follow the previous brief: devnet only, `sponsors/solana/` only, branch `sponsor/solana`. Memos carry the file
sha256 and the commit date, not the commit hash.

Rules: no keys in git; no "Co-Authored-By" or AI trailer lines; report problems rather than fixing the paper
yourself (Ojasva's revision rounds apply the fixes).
