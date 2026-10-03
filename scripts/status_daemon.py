"""Writes docs/live/status.json every 5 s for the Mission Control page (docs/live/control.html).

    .venv/bin/python scripts/status_daemon.py
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

OUT = Path("docs/live/status.json")
HPG = ["ssh", "-S", os.path.expanduser("~/.ssh/cm-hpg"), "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
       "ojasvamishra@hpg.rc.ufl.edu", "squeue -u $USER -h -o '%i|%j|%T|%M'"]


def jload(p):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return None


def pgrep(pat):
    r = subprocess.run(["pgrep", "-f", pat], capture_output=True, text=True)
    return [x for x in r.stdout.split() if x]


def newest(paths):
    fs = [p for p in paths if os.path.exists(p)]
    return max((os.path.getmtime(p) for p in fs), default=0)


def tree_mtime(d):
    m = 0
    for root, _, files in os.walk(d):
        for f in files:
            try:
                m = max(m, os.path.getmtime(os.path.join(root, f)))
            except OSError:
                pass
    return m


def main():
    prev_sizes, hpg, hpg_t = {}, [], 0
    while True:
        now = time.time()
        rec = []
        for name, pat, files in (("Order-book recorder", "src.live_recorder", "data/live/market_*.jsonl"),
                                 ("Score-feed + side-market recorder", "recorder.py", "data/live_v2/clob_*.jsonl")):
            fs = sorted(glob.glob(files))
            f = fs[-1] if fs else None
            size = os.path.getsize(f) if f else 0
            rate = (size - prev_sizes.get(name, size)) / 5 / 1024
            prev_sizes[name] = size
            rec.append({"name": name, "running": bool(pgrep(pat)), "file_mb": round(size / 1e6, 1), "kb_per_s": round(max(rate, 0), 1),
                        "last_write_s": round(now - os.path.getmtime(f), 1) if f else None})
        if now - hpg_t > 60:
            hpg_t = now
            try:
                r = subprocess.run(HPG, capture_output=True, text=True, timeout=15)
                hpg = [dict(zip(("id", "name", "state", "time"), l.split("|"))) for l in r.stdout.splitlines() if l.strip()]
            except Exception:
                hpg = [{"id": "-", "name": "unreachable", "state": "-", "time": "-"}]
        wf = []
        for name, done_file, work_dir in (
                ("Tier-0 backtest: CV + live feed, full pipeline", "results/tier0/results.json", "research/v2/tier0"),
                ("Blind test on ~26k never-examined matches", "results/expand/results.json", "research/v2/expand"),
                ("COURTSIDE engine: vision → execution (paper)", "results/engine/demo_run.json", "engine")):
            act = max(tree_mtime(work_dir), newest([done_file]))
            wf.append({"name": name, "done": os.path.exists(done_file), "last_activity_s": round(now - act) if act else None})
        c = jload("results/v2/causal.json") or {}
        s = jload("results/summary.json") or {}
        hl = {}
        if c:
            hl["v2 in sample"] = f"+{c['causal/is_eval/slip0.0']['per_share_c']:.2f}¢/share · Sharpe {c['causal/is_eval/slip0.0']['sharpe_ann']:.1f}"
            hl["v2 out of sample"] = f"+{c['causal/burned_oos/slip0.0']['per_share_c']:.2f}¢/share · Sharpe {c['causal/burned_oos/slip0.0']['sharpe_ann']:.1f}"
        if s.get("h4"):
            hl["Book vs public score feed"] = f"book first {s['h4']['share_book_first']*100:.0f}% · median {s['h4']['median_lead_s']:.0f} s ahead"
        fw = jload("results/v2/forward.json")
        hl["Forward test (blind)"] = (fw.get("verdict_A_fast_tier", "?") + " / " + fw.get("verdict_B_v2_book", "?")) if fw else "scheduled ~11:30 UTC"
        for k, p in (("Tier-0 scenario", "results/tier0/results.json"), ("Unseen-match test", "results/expand/results.json")):
            hl[k] = "done: see results" if os.path.exists(p) else "running"
        git = subprocess.run(["git", "log", "-6", "--format=%cr|%s"], capture_output=True, text=True).stdout.splitlines()
        du = shutil.disk_usage(os.path.expanduser("~"))
        OUT.write_text(json.dumps({"t": now, "recorders": rec, "hpg": hpg, "workflows": wf, "headline": hl,
                                   "disk_free_gb": round(du.free / 1e9, 1), "git": [g.split("|", 1) for g in git]}))
        time.sleep(5)


if __name__ == "__main__":
    main()
