# Yoan: help finish the paper (updated Sun Oct 4, ~2:45 AM; hard stop 8:30 AM EDT)

**Drop ElevenLabs.** It isn't worth the time. Everything below feeds the one thing that is judged: the 5-page quant
note plus a public repo that judges can run.

**Stop merging PRs into main.** Main gets rewritten and force-pushed this morning. Push only your own branches, or
just send results to Ojasva.

## Why this matters
Judges spot-check that our code runs and gives the same numbers as the note. If it doesn't, the Performance score
is capped at 4/10. Our README admits the full chain "was last run end to end on the authors' machine, not on a clean
clone". You are the clean clone. Your run lets us say "reproduced on a teammate's clean machine". That is
real evidence, and it can catch a problem while there's still time to fix it.

## 1. Full clean-clone reproduction from the snapshot branch (start NOW; most of it runs unattended)
Get the latest code from the temporary branch `snapshot-0300` on our repo: the full repo as of 3 AM, including
tonight's work. The branch is deleted after the final push.
```bash
git clone --branch snapshot-0300 --single-branch https://github.com/OjasMishra32/computervisionpredictivetabletennismoneymachineouuushiii cc_test && cd cc_test   # new folder, nothing reused
python3 --version            # note it (README says tested on 3.12 Linux and 3.14 macOS)
bash run.sh setup            # ~1 min
bash run.sh replay           # ~1 min, no network
bash run.sh redteam          # checks every derived number against its results file
bash run.sh tests            # ~2-7 min
bash run.sh data             # public Polymarket crawl, ~1-2 h, no keys, resumable: leave it running
bash run.sh reproduce        # ~15-20 min: every result file, figure and the paper
```
- Write down every command, how long it took, and the full error output whenever something fails.
- If a step fails, try the obvious fix on your copy only (missing package, Python version) and note exactly what
  you did.
- Do not push fixes.
- After `reproduce`, run `git status --short results/` and `git diff --stat results/`. Changed result files are
  where the numbers moved. Send Ojasva the list of changed files and, for the paper's headline files
  (`results/v2/*.json`, `results/tier0_v3/*/results.json`, `results/e2e/summary.json`,
  `results/capacity/*`, `results/fresh_holdout/results.json`), the old vs new values.
- Send a first update after setup/replay/redteam/tests, about 15 minutes in, so problems surface early. Send the
  full report when `reproduce` finishes.

## 2. Read the paper as a judge (about 30 minutes, while the crawl runs)
Ojasva sends you the current PDF. Read pages 1–5 only; judges don't have to read the appendix. Keep the organizers'
track page open: https://www.gqhacks.com/tracks/systematic-trading (rubric, "what judges want", pitfalls, the
checklist). Send back short bullets:
- **The 5 places a judge would get confused or stop believing us,** with page and sentence.
- **Any number that has no visible support** on the page: a table, a figure, or a cited file.
- **Gaps against the organizers' list.** Their minimum metrics, for in-sample and out-of-sample, are annual return,
  volatility, Sharpe, max drawdown, turnover and an equity curve. Do we cover them, plus costs in bps and
  doubled, number of variants tried, and what failed? Is any missing or hard to find?
- **Anything that reads like hype rather than a plain student note.**

Be blunt. Ojasva feeds this straight into the next revision round.

## 3. Check the references (about 20 minutes)
In your clone, open `docs/paper/refs.bib` and the references page of the PDF. For each entry:
- Confirm it exists, with the right authors, year, title and venue. Use Google Scholar or the publisher page.
- Confirm the sentence citing it says something the source actually supports.

Send a list of fixes, as `bib key: problem → correct value`.

## 4. Devpost page (checklist item: "All team members listed on Devpost")
- Ask Ojasva whether he wants to own the project, then make a draft on gqhacks.devpost.com:
  - **team:** Ojasva Mishra, Yoan Exposito, Rafael Penhas, Ian Hoang (all four accept)
  - **track:** Systematic Trading
  - **repo:** https://github.com/OjasMishra32/computervisionpredictivetabletennismoneymachineouuushiii
- Prize opt-ins:
  - MLH Best Use of Vultr
  - MLH Best Use of Snowflake API
  - MLH Best Use of Tiger Data
  - MLH Best Use of Solana, only if Ian pushes it
  - No ElevenLabs prizes
- Paste the "Devpost copy" from `sponsors/vultr`, `sponsors/snowflake` and `sponsors/tigerdata` READMEs.
- Ojasva uploads the final PDF. **Don't press final submit until he says.** Devpost closes at 11:00 AM sharp.

## 5. Last: quick re-test on the public repo (when Ojasva says "final push done", about 6–8 AM)
Make a fresh `git clone` of the public repo. Run `bash run.sh setup`, `bash run.sh redteam` and `bash run.sh tests`,
and check that the README's commands still match what exists. That covers the paper files moving out and the
history rewrite. Report anything broken.
