# Rafael: help finish the paper (Sun Oct 4, ~2:50 AM; hard stop 8:30 AM EDT)

Your Tiger Data work (Tick Store + Live Lab) is on our main with your name on it. Thank you.

What is judged: the 5-page quant note (PDF) plus a public repo that judges can run. There is no talk and no Q&A,
and live trading isn't scored. Judges skim, so anything hard to read or hard to find costs points.

**Don't merge PRs into main.** Main gets rewritten and force-pushed this morning. Just send your findings to Ojasva.

Ojasva sends you the current PDF and `courtside_latest_0239.bundle` (354 MB, the full repo as of 2:39 AM, private).
To get a working copy:
```bash
git clone courtside_latest_0239.bundle raf_check && cd raf_check
```

## 1. Figures and tables, at the size a judge sees them (about 30 minutes)
Open pages 1–5 at 100% zoom, then print one page or view it in grayscale. For every figure and table, check:
- **Readable at print size:** no tiny axis labels or overlapping text, legends don't hide data, units are on every
  axis.
- **Works in grayscale and for colour-blind readers:** lines and bars are distinguishable without colour.
- **The caption says what to conclude,** not just what's plotted. Simulated or counterfactual numbers say so in
  the caption.
- **The text cites it,** and the numbers in the figure match the numbers in the text.

Send bullets: figure/table number, problem, suggested fix.

## 2. The organizers' 9 pitfalls, one by one (about 30 minutes)
Use the "Pitfalls" chapter of https://www.gqhacks.com/tracks/systematic-trading:
p-hacking, overfitting, look-ahead, survivorship, ignoring costs, leaking the test set, misleading Sharpe, regime
dependence, unrealistic capacity. For each, find where pages 1–5 show we checked it. Send a table:
`pitfall | page/section where we address it | convincing? (yes/weak/missing) | fix`.

Watch especially for these:
- **Misleading Sharpe.** Their page says "a Sharpe above 3 on daily data usually means a bug". Ours are 7–15, so
  the paper must explain why next to the number.
- **Regime dependence.** Does any one month or event carry the profit?
- **Survivorship.** Voided or cancelled markets, retirements, walkovers.

## 3. The repo as a judge first sees it (about 30 minutes)
In your clone:
- Read `README.md` top to bottom as a stranger would. Is the setup clear? Is it obvious which single command
  reproduces the headline numbers?
- Check that every relative link and path in the README exists in the repo. A short script works:
  `grep -o '](\S*)' README.md` → test each path.
- Check `requirements.txt` installs cleanly in a fresh venv. Note any package that fails or needs a system library.
- Check for anything that shouldn't be public:
  - stray big files: `git ls-files | xargs ls -la | sort -k5 -n | tail`
  - personal paths in code (e.g. `/Users/...`, `/blue/...`) that a judge's machine wouldn't have
  - TODO / FIXME left in headline scripts

Send a list: file, line, problem.

## 4. If done early
Run `bash run.sh setup && bash run.sh replay && bash run.sh redteam` and send any error with its full output.

Send findings to Ojasva as soon as each part is done, ideally by 4:30 AM. The revision rounds running now apply the
true ones. Report only; don't edit the paper or push to main. No keys in git; no "Co-Authored-By" or AI trailer
lines.
