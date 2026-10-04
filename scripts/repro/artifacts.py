"""Which paper numbers reproduce.sh recomputes, and which come from committed artifacts (and why).

    python scripts/repro/artifacts.py write   # authors, after the final run: -> results/paper/committed_artifacts.json
    python scripts/repro/artifacts.py check   # reproduce.sh, last step: exit 1 unless every source of
                                              # results/paper/numbers.json was rewritten by this run or is a listed
                                              # committed artifact whose sha256 still matches

Every number in results/paper/numbers.json names its source file(s). `write` splits those files into
  recomputed  declared --out of a reproduce.sh step (always run), and
  committed   everything else: the file's sha256, its producer, the reproduce.sh step that would recompute it when
              an optional input is present (if any), and why it is not recomputed here.
A source that matches no entry of FAMILIES below stops `write` (exit 1): every committed artifact needs a stated
producer and reason. Documents and code cited as sources (HYPOTHESIS*.md, PREREG/DEVIATIONS files, src/*.py) are
listed separately; git pins them.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.repro.common import COMMITTED, REPRO, git_state, sha256_file, utc_now, write_json  # noqa: E402

SCHEMA = "courtside.paper.committed_artifacts/1"
NUMBERS = Path("results/paper/numbers.json")
REPRODUCE = Path("reproduce.sh")
PATH_RE = re.compile(r"((?:results|research|docs|src|models|data)/[\w./\-]+?\.(?:json|csv|log|md|parquet|py|txt|pkl)"
                     r"|results/live/STOPPED_TEAM_DECISION|HYPOTHESIS[\w]*\.md|DEVIATIONS[\w]*\.md)")
DOC_RE = re.compile(r"(\.md$|\.py$|^src/|STOPPED_TEAM_DECISION$)")

HPC = "HiPerGator batch job (hours of CPU/GPU); not part of the laptop reproduction"
LIVE = "measured on our hardware or recorded live order books (data/live, not distributed)"
# (glob, producer, family, why not recomputed). First match wins.
FAMILIES: list[tuple[str, str, str, str]] = [
    ("results/tier0/latency_sweep.*", "scripts/tier0_latency_sweep.py (hpg/tier0_latency_sweep.sbatch)",
     "CV latency sweep, conditional on realized >= 4c jumps (benchmark)", HPC),
    ("results/capacity/*", "scripts/capacity_study.py", "capacity grid on the jump-set and T3e books",
     "multi-hour grid over the jump-set and T3e books; not run by reproduce.sh"),
    ("results/tier0/results.json", "scripts/tier0_backtest.py", "original CV grid (jump set, benchmark)",
     "superseded research grid kept as the conditional benchmark; not rerun"),
    ("results/tier0/grid.csv", "scripts/tier0_backtest.py", "original CV grid (jump set, benchmark)",
     "superseded research grid kept as the conditional benchmark; not rerun"),
    ("results/tier0/inputs/*", "research/v2/tier0/rebuild.py", "CV simulator inputs (point mix, live points)",
     "frozen simulator inputs measured once from the live day's recorded points (data/live, not distributed)"),
    ("results/tier0_v3/*", "scripts/tier0_v3_optimise.py, scripts/tier0_v3_blind.py",
     "tier-0 v3 grid and its blind U2 test", "the blind test is evaluated once by design; U2 needs data/expand "
     "(an 11k-market crawl outside the universe)"),
    ("results/expand/*", "scripts/tier0_v3_blind.py", "U2 out-of-universe blind test",
     "evaluated once by design; needs data/expand (11k-market crawl outside the universe)"),
    ("results/lowloss/*", "scripts/lowloss_test.py", "v2-safe (lowloss) frozen evaluation incl. its U2 blind test",
     "pre-registered single run; U2 needs data/expand; not affected by the repair"),
    ("results/maker/*", "scripts/maker_oos.py", "maker v1 blind test", "evaluated once by design (blind)"),
    ("results/tt/*", "scripts/tier0_backtest.py", "table-tennis tier-0 study",
     "separate market (table tennis) crawl, not in the declared universe"),
    ("results/replay/*", "scripts/match_replay.py, match_replay_report.py, match_replay_check.py, "
     "match_replay_selective.py", "replay on recorded live order books", LIVE),
    ("results/risk/risk_stats.json", "scripts/risk_stats.py", "risk statistics across books",
     "needs gitignored spin raw data and data/expand"),
    ("results/rigor/rigor.json", "scripts/rigor_pack.py", "DSR / PBO / block bootstrap pack",
     "statistics over committed result series; the script also rewrites research/rigor/RESULTS.md; not run by "
     "reproduce.sh"),
    ("results/alpha/*", "scripts/alpha_pack.py", "alpha summary pack", "summary of committed results; not rerun"),
    ("results/financials/financials.json", "scripts/financials.py", "financial scenario tables",
     "built from committed results; not rerun"),
    ("results/financials/pm_compute.json", "scripts/pm_compute.py", "compute cost estimate", "static cost inputs"),
    ("results/decay/*", "scripts/signal_decay.py, research/decay/audit_sameblock.py", "signal decay",
     "reads data/expand and the prints of every block; not rerun"),
    ("results/e2e/*", "scripts/cv_showcase.py (end-to-end latency run)", "end-to-end latency measurement", LIVE),
    ("results/engine/demo_run_L4.json", "engine/vision/demo_live.py", "engine demo run", LIVE),
    ("results/engine/live_market_run.json", "engine/run.py --mode live-market", "engine on live books", LIVE),
    ("results/engine/online_vs_offline.json", "engine/vision/eval_online.py", "online vs offline vision calls",
     "vision evaluation on the held-out clip with the frozen model (GPU/HPC); not rerun"),
    ("results/engine/vision_bench.json", "engine/vision/run_demo.py, bench_summary.py", "vision latency bench",
     "hardware latency measurement (bash run.sh cv measures it again on the judge's machine)"),
    ("results/webrtc/*", "scripts/webrtc_latency.py, webrtc_verify.py", "WebRTC latency measurement", LIVE),
    ("results/home_stream/*", "research/home_stream (not distributed)", "home-stream latency routes", LIVE),
    ("results/live/*", "scripts/live_paper.py", "stopped live paper session (not used for results)", LIVE),
    ("results/spin/*", "scripts/spin_tennis_report.py, research/spin/tt_report.py (hpg/spin_tt.sbatch)",
     "spin estimation", HPC),
    ("results/tennis_tracking/*", "src/tennis_tracking/run_eval.py (hpg/tennis_eval.sbatch)", "tennis ball tracking",
     HPC),
    ("results/tracking/*", "src/tracking/summarize.py (hpg/track_*.sbatch)", "table-tennis ball tracking", HPC),
    ("results/viz/*", "scripts/tennis_real_tracked.py", "real tennis footage detections", HPC),
    ("results/cv_teaser/bounce_example.json", "scripts/cv_teaser_fig.py extract --work <run_eval.py work dir>",
     "vision teaser: one held-out bounce from the tracking work table", HPC + " (the run_eval work table)"),
    ("results/redteam/causal_cv.json", "scripts/redteam_causal_cv.py", "red-team causal-CV diagnostic",
     "diagnostic re-simulation that re-reads held-out cells; not part of the paper pipeline"),
    ("results/oos_peeks.log", "append-only log of held-out reads", "provenance record",
     "a record, not a computation; reproduction runs never append to it (results/repro/reads.log instead)"),
    ("results/v2/forward.json", "scripts/forward_test.py", "forward test (not run, HYPOTHESIS_V2.md A5)", "not run"),
    ("research/*", "research/<study>/*.py", "research-phase studies cited as context",
     "research-phase measurements and diagnostics with partly gitignored or live inputs; cited, not rerun"),
]


def sources(numbers: dict) -> dict[str, list[str]]:
    """source path -> numbers.json keys that cite it."""
    out: dict[str, list[str]] = {}
    for key, v in numbers.get("numbers", {}).items():
        for m in set(PATH_RE.findall(str(v.get("source", "")))):
            out.setdefault(m, []).append(key)
    return out


def steps(text: str) -> list[dict]:
    """reproduce.sh steps: lines `step <id> [--out P]... [--skip-unless P --skip-reason T] -- <cmd>`."""
    out = []
    for raw in text.replace("\\\n", " ").splitlines():
        line = raw.split(" #", 1)[0].strip()
        if not line.startswith("step "):
            continue
        toks = shlex.split(line)
        if "--" not in toks:
            continue
        i = toks.index("--")
        head, cmd = toks[1:i], toks[i + 1:]
        st = {"id": head[0], "outs": [], "skip_unless": None, "cmd": " ".join(cmd)}
        j = 1
        while j < len(head):
            if head[j] == "--out":
                st["outs"].append(head[j + 1]); j += 2
            elif head[j] == "--skip-unless":
                st["skip_unless"] = head[j + 1]; j += 2
            elif head[j] == "--skip-reason":
                j += 2
            else:
                j += 1
        out.append(st)
    return out


def family(path: str):
    for pat, producer, fam, why in FAMILIES:
        if fnmatch.fnmatch(path, pat):
            return producer, fam, why
    return None


def write(root: Path = ROOT) -> int:
    numbers = json.loads((root / NUMBERS).read_text())
    src = sources(numbers)
    st = steps((root / REPRODUCE).read_text())
    always = {o: s["id"] for s in st if not s["skip_unless"] for o in s["outs"]}
    conditional = {o: s for s in st if s["skip_unless"] for o in s["outs"]}
    recomputed, committed, docs, absent, unclassified = [], [], [], [], []
    for path, keys in sorted(src.items()):
        if path.startswith("results/") and not (root / path).exists() and path not in always and all(
                "absent" in str(numbers["numbers"][k].get("source", "")) for k in keys):
            absent.append({"path": path, "n_paper_keys": len(keys), "paper_keys": sorted(keys),
                           "note": "the paper cites this file's absence (e.g. a test that was not run)"})
            continue
        if path in always:
            recomputed.append({"path": path, "step": always[path], "n_paper_keys": len(keys)})
            continue
        if DOC_RE.search(path) and path not in conditional and not path.startswith("results/"):
            docs.append({"path": path, "n_paper_keys": len(keys), "pinned_by": "git"})
            continue
        p = root / path
        if path in conditional:
            s = conditional[path]
            entry = {"producer": s["cmd"], "family": "recomputed only when an optional input is present",
                     "why_not_recomputed": f"reproduce.sh step {s['id']} runs only when {s['skip_unless']} exists "
                                           "(not distributed); otherwise this committed file is used",
                     "recompute_step": s["id"]}
        else:
            f = family(path)
            if f is None:
                unclassified.append(path)
                continue
            entry = {"producer": f[0], "family": f[1], "why_not_recomputed": f[2], "recompute_step": None}
        if not p.exists():
            unclassified.append(f"{path} (cited but missing)")
            continue
        committed.append({"path": path, "sha256": sha256_file(p), "bytes": p.stat().st_size, **entry,
                          "n_paper_keys": len(keys), "paper_keys": sorted(keys)[:12]})
    if unclassified:
        for u in unclassified:
            print(f"artifacts write: no producer/reason for paper source {u} (add it to FAMILIES or to a "
                  "reproduce.sh step's --out)", file=sys.stderr)
        return 1
    n_keys = len(numbers.get("numbers", {}))
    keys_rec = {k for r in recomputed for k in src[r["path"]]}
    keys_com = {k for c in committed for k in src[c["path"]]}
    out = {
        "schema": SCHEMA, "generated_utc": utc_now(), "git_head": git_state(root)["git_head"],
        "numbers_sha256": sha256_file(root / NUMBERS),
        "summary": {"paper_keys": n_keys,
                    "keys_citing_a_recomputed_file": len(keys_rec),
                    "keys_citing_only_committed_artifacts": len(keys_com - keys_rec),
                    "recomputed_files": len(recomputed), "committed_artifacts": len(committed),
                    "documents_and_code": len(docs), "cited_as_absent": len(absent)},
        "note": "A committed artifact is the authors' output, checked here only by sha256. scripts/repro/artifacts.py "
                "check fails a reproduction if one changed without its producer running, or if a paper source is "
                "neither recomputed nor listed.",
        "recomputed": recomputed, "committed": committed, "documents_and_code": docs, "cited_as_absent": absent,
    }
    write_json(root / COMMITTED, out)
    s = out["summary"]
    print(f"committed artifacts: {s['recomputed_files']} source files recomputed by reproduce.sh, "
          f"{s['committed_artifacts']} committed artifacts, {s['documents_and_code']} documents/code -> {COMMITTED}")
    return 0


def check(root: Path = ROOT) -> int:
    numbers = json.loads((root / NUMBERS).read_text())
    src = sources(numbers)
    run = json.loads((root / REPRO / "run_manifest.json").read_text())
    rewritten = {p for s in run.get("steps", []) for p in (s.get("declared_outputs") or [])
                 if p not in (s.get("stale_outputs") or []) and s.get("exit") == 0}
    listing = json.loads((root / COMMITTED).read_text())
    listed = {c["path"]: c for c in listing.get("committed", [])}
    docs = {d["path"] for d in listing.get("documents_and_code", [])}
    absent = {d["path"] for d in listing.get("cited_as_absent", [])}
    problems, n_rec, n_com = [], 0, 0
    for path in sorted(src):
        if path in absent:
            if (root / path).exists():
                problems.append(f"{path}: the paper cites its absence but it exists now")
            continue
        if path in rewritten:
            n_rec += 1
        elif path in listed:
            p = root / path
            if not p.exists():
                problems.append(f"{path}: listed committed artifact is missing")
            elif sha256_file(p) != listed[path]["sha256"]:
                problems.append(f"{path}: committed artifact changed but its producer did not run in this "
                                "reproduction (sha256 differs from results/paper/committed_artifacts.json)")
            else:
                n_com += 1
        elif path in docs or (DOC_RE.search(path) and not path.startswith("results/")):
            continue
        else:
            problems.append(f"{path}: cited by the paper but neither recomputed in this run nor a listed "
                            "committed artifact")
    rep = {"schema": "courtside.repro.artifact_check/1", "checked_utc": utc_now(), "ok": not problems,
           "sources_recomputed": n_rec, "sources_committed_verified": n_com, "problems": problems}
    write_json(root / REPRO / "artifact_check.json", rep)
    for p in problems:
        print(f"artifacts check: {p}", file=sys.stderr)
    print(f"artifacts check: {'ok' if not problems else 'FAILED'}: {n_rec} paper source files recomputed in this "
          f"run, {n_com} committed artifacts verified by sha256, {len(problems)} problem(s)")
    return 0 if not problems else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["write", "check"])
    a = ap.parse_args(argv)
    return write() if a.cmd == "write" else check()


if __name__ == "__main__":
    sys.exit(main())
