# Handoff: Rafael — Gemini sponsor prize ("COURTSIDE Analyst")

**Owner:** Rafael Penhas · **Load: light (about 2-3 hours of agent work)** · **Deadline:** branch pushed by **9:00 AM EDT
Sun Oct 4** (Devpost closes 11:00 AM EDT)
**Prize targeted (opt in on Devpost when submitting):** **MLH: Best Use of Gemini API** — "build AI-powered apps that make
your friends say WHOA ... create an app that summarizes complex research papers."
*Stretch, only after 1a works:* **MLH: Best Use of Snowflake API** (Raspberry Pi 4) — see §1c.

Give this whole file to your AI coding agent as its brief. It is self-contained.

---

## 0. What COURTSIDE is (read this first, 2 minutes)

COURTSIDE is our Gator Quant Hacks 2026 Systematic Trading submission (team: Ojasva Mishra, Yoan Exposito, Rafael Penhas,
Ian Hoang). Thesis: in-play tennis prices on Polymarket are set by whoever learns the point first; we measure what each
second of speed is worth, and our computer vision (CV) calls points before the ball lands. Everything is **paper trading
only**. Ojasva is finalising the paper/video/deck; **you do not touch them**.

Repo: https://github.com/OjasMishra32/computervisionpredictivetabletennismoneymachineouuushiii

You only READ these:
- `docs/NOTE.md` / `docs/NOTE.pdf` — our quant paper (the final version lands tonight; pull before you finish).
- `docs/QA_PREP.md` — 28 hard judge questions with our answers and evidence.
- `results/paper/numbers.json` — every number in the paper with its source; `results/alpha/alpha.json`; `results/v2/causal.json`.
- `results/engine/online_events_L4.jsonl` — 172 CV calls (JSON lines: `call` MISS/BOUNCE, `p_miss`, `lead_ms`, ...).
- `results/engine/demo_run.json` — engine demo: calls mapped to paper orders/fills (illustrative, labelled).

## 1. What you build: "COURTSIDE Analyst" (Gemini API)

Two small pieces. Keep it simple and reliable.

### 1a. Ask-the-paper analyst (must have) — `sponsors/gemini/analyst.py`
- A command-line (and optional tiny local web page) Q&A over our work: `python sponsors/gemini/analyst.py "What is the
  break-even feed latency?"`.
- Context = `docs/NOTE.md` + `docs/QA_PREP.md` + `results/paper/numbers.json` (fits in Gemini's long context; no vector DB
  needed). System instruction: answer only from the provided documents, quote the exact number and its source key/section,
  say "not in our documents" otherwise, and keep the honesty labels (simulated 1 s licensed-feed baseline; post hoc vs
  pre-registered; paper trading only).
- Use a current Gemini model via the official `google-genai` Python SDK (e.g. `gemini-2.5-flash` for speed; note the model id
  in the README). Stream the answer.
- `--selftest`: run the 10 hardest questions from `docs/QA_PREP.md` and check each answer contains the right number
  (string match against `numbers.json`); print a pass/fail table. This shows judges it is grounded, not hallucinating.

### 1b. Trade explainer (should have) — `sponsors/gemini/explain_calls.py`
- For each CV call in `results/engine/online_events_L4.jsonl` (sample 10 MISS + 10 BOUNCE) and each paper fill in
  `results/engine/demo_run.json`, ask Gemini (structured JSON output) for a one-sentence plain-English explanation a
  first-time viewer understands ("The model saw the ball was going long 325 ms before it landed, so it called a miss;
  in tennis that point would move the match price about 4 cents"). Save `sponsors/gemini/out/explanations.json` and a small
  static `sponsors/gemini/out/explanations.html`. Numbers must come from the event row (pass them in; tell the model not
  to invent any).

### 1c. STRETCH — Gemini x Snowflake: the analyst queries our results in Snowflake (about 1.5 hours; only after 1a works)
- Free Snowflake trial account (30 days). Credentials ONLY in `.env` (`SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PASSWORD`
  or key-pair, `SNOWFLAKE_WAREHOUSE`, `SNOWFLAKE_DATABASE`), gitignored; never print/commit them.
- `sponsors/snowflake/load.py`: create tables and load our committed result files with the Snowflake Python connector
  (`write_pandas`): `results/tier0/latency_sweep.csv` (profit/Sharpe by feed latency), `results/capacity/*.csv|json`
  (capacity grid), `results/v2/causal.json` + `results/v2/cost_stress.json` (flattened), `results/engine/online_events_L4.jsonl`
  (CV calls), `results/e2e/trace.jsonl` (pipeline stage times). Small tables; no raw market data.
- `sponsors/gemini/analyst.py --sql` mode: give Gemini a function-calling tool `run_sql(query)` that runs **read-only SELECT**
  queries against Snowflake (reject anything else in code), plus the table schemas; numeric questions ("What Sharpe do we get
  at a 0.5 s feed, pre-registered reading?", "How much capital before Sharpe halves?") are answered by SQL over the real tables,
  and the answer shows the SQL it ran.
- Rules: folder ownership `sponsors/snowflake/` + `sponsors/gemini/`; read-only queries from the model; no secrets in git.
- Devpost line: "**Snowflake:** our results tables (latency sweep, capacity grid, CV calls, pipeline timings) live in Snowflake,
  and the Gemini analyst answers numeric questions by writing and running read-only SQL against them, showing its query."

## 2. Rules (hard)
- **Folder ownership: you may only create/edit files under `sponsors/gemini/` (and `sponsors/snowflake/` for the stretch).** Do NOT edit anything else (no edits to
  docs/, results/, engine/, scripts/, README.md, requirements.txt). Zero merge conflicts.
- **API key:** free key from Google AI Studio (https://aistudio.google.com/apikey). Put it ONLY in `.env` at the repo root
  as `GEMINI_API_KEY=...` (gitignored). Never print/commit/paste it. Load it with a few lines of code (no new dependency
  needed beyond `google-genai`; list it in `sponsors/gemini/requirements.txt`).
- **Honesty:** the analyst must not claim real trading, live match video, licensed feeds or profits we didn't show; it
  repeats our labels. No personal data.
- **Commits:** plain messages, **no "Co-Authored-By" / AI-attribution trailers** (team rule).

## 3. Setup
```bash
git clone https://github.com/OjasMishra32/computervisionpredictivetabletennismoneymachineouuushiii courtside && cd courtside
git checkout -b sponsor/gemini
python3 -m venv .venv && .venv/bin/pip install google-genai
echo 'GEMINI_API_KEY=<your key>' >> .env   # never commit
```

## 4. Hand back (no merge conflicts)
- Push: `git push origin sponsor/gemini`; open a PR "Gemini: COURTSIDE Analyst".
- Do NOT merge or rebase main into your branch (main's history gets rewritten tonight). Ojasva copies your folder onto main
  with `git checkout sponsor/gemini -- sponsors/gemini`.
- PR description: what you built, how to run (≤ 3 commands), the self-test table, the model id, and the Devpost text below.

## 5. Definition of done
- [ ] `python sponsors/gemini/analyst.py "How fast is the pipeline from frame to order?"` answers with the number + source.
- [ ] `python sponsors/gemini/analyst.py --selftest` prints a pass/fail table on 10 questions (target ≥ 9/10).
- [ ] `python sponsors/gemini/explain_calls.py` writes `out/explanations.json` (+ `.html`).
- [ ] `sponsors/gemini/README.md`: what, how to run, model, self-test result, honesty notes.
- [ ] No key in git (`git grep -n AIza` returns nothing).

## 6. Devpost text (fill in and give to Ojasva)
**Gemini — COURTSIDE Analyst.** Our quant paper is dense, so we built an analyst on the Gemini API that answers any
question about COURTSIDE straight from our paper, Q&A sheet and results file, quoting the exact number and where it came
from (it passes <N>/10 of our hardest judge questions in a self-test). Gemini also turns every computer-vision call and
paper trade into a one-sentence plain-English explanation for first-time viewers. Grounded in our documents only; paper
trading only.
