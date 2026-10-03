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


WF_ROOT = Path(os.path.expanduser("~/.claude/projects")) / (
    "-Users-ojasvamishra32-Library-Application-Support-Claude-scratch-workspaces-7bb77844-b795-43aa-a67b-63736f9e8f62-"
    "8080cf91-fcd1-4d20-84cd-23ff24f77beb-scratch-2026-10-03-f34211") / "ec7c96ab-096e-46da-b14c-14c93f0528c1" / "subagents" / "workflows"
WF_NAMES = {"wf_057b300e": "Spin-aware CV", "wf_0fbb8784": "CV-edge backtest", "wf_7f9708bf": "Engine",
            "wf_9626758c": "Rubric audit", "wf_04c8923d": "Live paper + side-market maker", "wf_818c1058": "Table tennis + signal decay",
            "wf_5ffa44bc": "Financials + risk", "wf_c424cd8a": "CV-edge v3 (optimise → blind)", "wf_b83d1a35": "Rigor pack"}
REPO = str(Path.cwd())
FIGS = Path("docs/live/figs")


def _tail_json(path, nbytes=96_000):
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2); size = fh.tell(); fh.seek(max(0, size - nbytes))
            lines = fh.read().decode("utf-8", "replace").splitlines()[1:]
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except Exception:
            pass
    return out


def _clean(t):
    t = (t or "").replace(REPO + "/", "").replace(REPO, ".").replace('cd "." && ', "").replace("cd . && ", "")
    return " ".join(t.split())[:150]


def agent_activity(now):
    """Running workflow agents: what each is doing right now, plus a merged recent-activity feed."""
    agents, feed = [], []
    if not WF_ROOT.exists():
        return agents, feed
    for d in WF_ROOT.iterdir():
        j = d / "journal.jsonl"
        if not j.exists() or now - j.stat().st_mtime > 6 * 3600 and now - tree_mtime(d) > 600:
            continue
        started, done = {}, set()
        for e in _tail_json(j, 2_000_000):
            if e.get("type") == "started":
                started[e.get("agentId")] = (e.get("label", ""), e.get("phase", ""))
            elif e.get("type") == "result":
                done.add(e.get("agentId"))
        wname = WF_NAMES.get(d.name[:11], d.name)
        for aid, (label, phase) in started.items():
            if aid in done:
                continue
            f = d / f"agent-{aid}.jsonl"
            if not f.exists():
                continue
            last, n_tools = None, 0
            for e in _tail_json(f):
                if e.get("type") != "assistant":
                    continue
                ts = e.get("timestamp", "")
                for c in (e.get("message", {}).get("content") or []):
                    if not isinstance(c, dict):
                        continue
                    if c.get("type") == "tool_use":
                        inp = c.get("input") or {}
                        what = inp.get("description") or inp.get("command") or inp.get("file_path") or inp.get("pattern") or ""
                        if c.get("name") in ("Write", "Edit") and inp.get("file_path"):
                            what = f"{c['name']} {inp['file_path']}"
                        item = {"wf": wname, "agent": label, "tool": c.get("name"), "what": _clean(str(what)), "ts": ts}
                        feed.append(item); last = item; n_tools += 1
                    elif c.get("type") == "text" and c.get("text", "").strip():
                        item = {"wf": wname, "agent": label, "tool": "note", "what": _clean(c["text"]), "ts": ts}
                        feed.append(item); last = item
            age = now - f.stat().st_mtime
            if age > 1800:  # retried or abandoned starts
                continue
            agents.append({"wf": wname, "agent": label, "phase": phase, "now": (last or {}).get("what", "starting"),
                           "tool": (last or {}).get("tool", ""), "idle_s": round(age)})
    feed.sort(key=lambda x: x["ts"], reverse=True)
    agents.sort(key=lambda a: a["idle_s"])
    return agents, feed[:40]


def gallery(now, keep=16):
    """Newest result figures, copied next to the page so the static server can show them."""
    FIGS.mkdir(parents=True, exist_ok=True)
    pngs = [p for p in glob.glob("results/**/*.png", recursive=True) + glob.glob("research/**/*.png", recursive=True)
            if now - os.path.getmtime(p) < 14 * 3600 and "/raw/" not in p and "/frames/" not in p]
    pngs.sort(key=os.path.getmtime, reverse=True)
    out = []
    for p in pngs[:keep]:
        dst = FIGS / p.replace("/", "__")
        if not dst.exists() or os.path.getmtime(dst) < os.path.getmtime(p):
            try:
                shutil.copy2(p, dst)
            except OSError:
                continue
        out.append({"src": p, "url": f"figs/{dst.name}", "age_s": round(now - os.path.getmtime(p))})
    return out


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
                ("Tier-0 v3: optimise → freeze → blind test", "results/tier0_v3/blind.json", "research/v2/tier0_v3"),
                ("Side-market maker: blind OOS test", "results/maker/oos.json", "research/v2/maker"),
                ("Live paper session on real markets (until 11:30 UTC)", "results/live/FINAL", "results/live"),
                ("Table tennis: every Polymarket match, blind test", "results/tt/results.json", "research/tt"),
                ("Signal decay vs latency", "results/decay/decay.json", "research/decay"),
                ("Financials + risk register", "results/financials/financials.json", "research/financials")):
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
        if t0 and "headline" in t0:
            hi, ho = t0["headline"]["IS"]["mean"], t0["headline"].get("burned_OOS", t0["headline"].get("OOS", {})).get("mean", {})
            hl["CV-edge (assumed data)"] = (f"IS {hi['per_share_c']:+.2f}¢ · Sharpe {hi['sharpe_ann']:.1f} · "
                                            f"OOS {ho.get('per_share_c', float('nan')):+.2f}¢ · Sharpe {ho.get('sharpe_ann', float('nan')):.1f} "
                                            "(revised; sign hinges on unmeasured reprice timing)")
        elif t0:
            hl["CV-edge (assumed data)"] = "first result refuted by verifier (fill price); revised numbers pending"
        mk = jload("results/maker/oos.json")
        if mk:
            hl["Side-market maker, blind OOS"] = "FAIL: +1.87¢ [−0.14, 3.86], −$379"
        lv = jload("results/live/summary.json")
        if lv:
            hl["Live paper (real markets)"] = lv.get("headline") or json.dumps(lv)[:120]
        rg = jload("results/rigor/rigor.json")
        hl["Rigor pack"] = "OOS PSR vs 0: 0.987 · PBO ~9–24% (verified)" if rg else "running"
        cs = jload("results/v2/cost_stress.json")
        if cs:
            hl["Costs doubled"] = (f"IS {cs['is_eval/fee_x2']['per_share_c']:+.2f}¢ · "
                                   f"OOS {cs['burned_oos/fee_x2']['per_share_c']:+.2f}¢ (fees ×2)")
        git = subprocess.run(["git", "log", "-6", "--format=%cr|%s"], capture_output=True, text=True).stdout.splitlines()
        du = shutil.disk_usage(os.path.expanduser("~"))
        try:
            agents, feed = agent_activity(now)
        except Exception as ex:  # never let the dashboard die
            agents, feed = [{"wf": "dashboard", "agent": "error", "phase": "", "now": str(ex)[:120], "tool": "", "idle_s": 0}], []
        try:
            figs = gallery(now)
        except Exception:
            figs = []
        OUT.write_text(json.dumps({"t": now, "agents": agents, "feed": feed, "figs": figs,
                                   "recorders": rec, "hpg": hpg, "workflows": wf, "headline": hl,
                                   "disk_free_gb": round(du.free / 1e9, 1), "git": [g.split("|", 1) for g in git]}))
        time.sleep(5)


if __name__ == "__main__":
    main()
