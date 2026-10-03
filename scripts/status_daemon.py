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
                ("CV-edge backtest (tier 0) + verifiers", "results/tier0/VERIFIED", "research/v2/tier0"),
                ("Blind test on 11,307 unseen markets", "results/expand/results.json", "research/v2/expand"),
                ("v2-safe (risk dial), blind-tested", "results/lowloss/results.json", "research/v2/lowloss"),
                ("COURTSIDE engine: vision → execution (paper)", "results/engine/demo_run.json", "engine"),
                ("Spin-aware CV (tennis filter + table-tennis Magnus fit)", "results/spin/tennis/RESULTS.md", "results/spin"),
                ("Rigor pack: deflated Sharpe, PBO, bootstrap", "results/rigor/rigor.json", "research/rigor"),
                ("Tier-0 v3: optimise → freeze → blind test", "results/tier0_v3/blind.json", "research/v2/tier0_v3")):
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
        e = jload("results/expand/results.json")
        if e:
            pr = e.get("primary", {})
            hl["Blind test, unseen markets"] = (f"IS {pr['u2_is']['per_share_c']:+.2f}¢ ({pr['u2_is']['label']}) · "
                                                f"OOS {pr['u2_oos']['per_share_c']:+.2f}¢ ({pr['u2_oos']['label']})")
        ll = jload("results/lowloss/results.json")
        if ll:
            hl["v2-safe"] = "worst day halved; blind OOS still fails (see paper)"
        fr = jload("results/v2/factor_regression.json")
        if fr:
            hl["Factor exposure"] = f"alpha t={fr['t']['alpha_daily']}, R²={fr['r2']} (not a market bet)"
        t0 = jload("results/tier0/results.json")
        if t0:
            pi, po = t0["primary"]["IS"], t0["primary"].get("burned_OOS", {})
            hl["CV-edge (assumed data)"] = f"Sharpe IS {pi['sharpe_ann']:.0f} · OOS {po.get('sharpe_ann', float('nan')):.0f} (being verified)"
        rg = jload("results/rigor/rigor.json")
        hl["Rigor pack"] = "done: see results/rigor" if rg else "running"
        git = subprocess.run(["git", "log", "-6", "--format=%cr|%s"], capture_output=True, text=True).stdout.splitlines()
        du = shutil.disk_usage(os.path.expanduser("~"))
        OUT.write_text(json.dumps({"t": now, "recorders": rec, "hpg": hpg, "workflows": wf, "headline": hl,
                                   "disk_free_gb": round(du.free / 1e9, 1), "git": [g.split("|", 1) for g in git]}))
        time.sleep(5)


if __name__ == "__main__":
    main()
