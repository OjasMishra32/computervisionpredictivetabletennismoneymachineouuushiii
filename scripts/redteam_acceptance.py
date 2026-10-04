"""Red-team acceptance checks for the integration pass (research/compliance/INTEGRATION_TODO.md §7), plus the
pending-input state the team needs at 11:20 UTC. Read-only: it greps text and reads JSON; it runs nothing.

    python scripts/redteam_acceptance.py            # table + results/redteam/acceptance.json; exit 0
    python scripts/redteam_acceptance.py --strict   # exit 1 if any FAIL (use before the final push)

Each check is PASS / FAIL / WARN / PENDING with the file and line that decides it. Heuristics are labelled as
such: a WARN means "a person should look", not "wrong". Two more states: KNOWN = a gap in the final video, which is
not re-rendered (each one is listed in research/compliance/FINAL_ISSUES.md); NOT RUN = an input the team decided not
to produce (the blind forward test, HYPOTHESIS_V2.md A5). Neither counts as a FAIL.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/redteam/acceptance.json"

PAPER = ["docs/paper/note.tex", "docs/paper/numbers.tex", "docs/NOTE.md"]
VIDEO = ["docs/video_script_60.md", "results/viz/courtside_60.srt"]   # the final video: its script and its subtitles
DECK = ["docs/deck/build_deck.py"]
PUBLIC = ["README.md", "docs/DEVPOST.md"]
TEAM = ["docs/QA_PREP.md"]
GROUPS = {"paper": PAPER, "video": VIDEO, "deck": DECK, "readme/devpost": PUBLIC}
FORBIDDEN = [r"calibrated from the data", r"goes live", r"stricter readings"]
OFFLINE_ONLY = [r"11/11", r"11 of 11", r"408\s*ms"]


def read(p: str) -> list[str]:
    f = ROOT / p
    return f.read_text(errors="replace").splitlines() if f.exists() else []


def hits(files, pattern, flags=re.I):
    out = []
    for p in files:
        for i, line in enumerate(read(p), 1):
            if re.search(pattern, line, flags):
                out.append(f"{p}:{i}: {line.strip()[:140]}")
    return out


def check(name, status, detail, where=None):
    return {"check": name, "status": status, "detail": detail, "where": where or []}


KNOWN_NOTE = "final video, not re-rendered: listed in research/compliance/FINAL_ISSUES.md"


def vfail(grp: str) -> str:
    """FAIL, or KNOWN for the final video (it is not re-rendered; the gap is listed for the main session)."""
    return "KNOWN" if grp == "video" else "FAIL"


def forward_not_run() -> str | None:
    """The amendment that last decided the forward test, if it says 'not run' (HYPOTHESIS_V2.md A3/A5)."""
    import re as _re
    f = ROOT / "HYPOTHESIS_V2.md"
    am = _re.findall(r"^## Amendment (A\d+) \([^)]+\): forward test ([^\n]+)", f.read_text(), _re.M) if f.exists() else []
    return am[-1][0] if am and "not run" in am[-1][1] else None


def deck_text() -> list[str]:
    try:
        from pptx import Presentation
    except Exception:  # noqa: BLE001
        return []
    f = ROOT / "docs/deck/courtside.pptx"
    if not f.exists():
        return []
    lines = []
    for k, s in enumerate(Presentation(str(f)).slides, 1):
        if s._element.get("show") == "0":       # hidden manifest slides list sources, not claims
            continue
        for sh in s.shapes:
            if sh.has_text_frame and sh.text_frame.text.strip():
                lines.append(f"slide {k} [{sh.name}]: " + " / ".join(x.strip() for x in sh.text_frame.text.splitlines() if x.strip()))
        if s.has_notes_slide:
            for t in s.notes_slide.notes_text_frame.text.splitlines():
                if t.strip():
                    lines.append(f"slide {k} notes: {t.strip()}")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()
    R = []

    # 1. forbidden phrases
    files = PAPER + VIDEO + DECK + PUBLIC        # QA_PREP lists these phrases on purpose (its never-say list)
    h = []
    for pat in FORBIDDEN:
        h += [x for x in hits(files, pat) if "never say" not in x.lower() and "never speak" not in x.lower()
              and "fail list" not in x.lower() and "grep" not in x.lower()]
    dt = [x for x in deck_text() if any(re.search(p, x, re.I) for p in FORBIDDEN)]
    R.append(check("1 forbidden phrases (calibrated from the data / goes live / stricter readings)",
                   "FAIL" if h or dt else "PASS", f"{len(h) + len(dt)} hit(s)", h + [f"courtside.pptx {x}" for x in dt]))

    # 2. pre-registered number before the post hoc P&L (heuristic: first line mentioning each)
    for grp, fl in GROUPS.items():
        for p in fl:
            L = read(p)
            if not L:
                continue
            pre = next((i for i, x in enumerate(L) if re.search(r"pre-?registered", x, re.I)
                        and re.search(r"break-?even|\$\s?4\b|4\.35|cv\.pre|t_oos_day|\+?4 a day", x, re.I)), None)
            post = next((i for i, x in enumerate(L) if re.search(r"\$\s?57|56\.59|\$\s?94|94\.35|cv\.cal\.oos\.usd|lc_oos_day", x)), None)
            if post is None:
                continue
            ok = pre is not None and pre <= post
            R.append(check(f"2 pre-registered before post hoc ({grp}: {p})", "PASS" if ok else "WARN",
                           f"first pre-registered line {None if pre is None else pre + 1}, first post hoc $ line {post + 1}"
                           " (heuristic)"))

    # 3. 'not ex ante' / 'selected on outcomes'
    for grp, fl in (("paper", PAPER[:2]), ("video", VIDEO), ("deck", DECK)):
        h = hits(fl, r"not ex ante|selected on outcomes")
        R.append(check(f"3 trade-set disclosure ({grp})", "PASS" if h else vfail(grp),
                       f"{len(h)} line(s) say 'not ex ante' or 'selected on outcomes'"
                       + ("" if h or grp != "video" else f" ({KNOWN_NOTE})"), h[:3]))

    # 4. offline CV numbers only with 'offline'
    bad = []
    for p in PAPER + VIDEO + DECK + PUBLIC:
        for i, line in enumerate(read(p), 1):
            if (any(re.search(x, line) for x in OFFLINE_ONLY) and not re.search(r"offline|look-?ahead", line, re.I)
                    and not re.search(r"11 (of|/) ?11 (calendar )?months|months?\W{0,3}(up|positive)|in 11 of 11|11/11 (up|down)", line)):
                bad.append(f"{p}:{i}: {line.strip()[:140]}")
    dl = deck_text()
    ctx = {}
    for x in dl:   # slide-level context: '11/11' next to a 'months' caption is the fast-tier month count
        ctx.setdefault(x.split(" [")[0].split(" notes")[0], []).append(x)
    bad += [f"courtside.pptx {x}" for x in dl if any(re.search(p, x) for p in OFFLINE_ONLY)
            and not re.search(r"offline|look-?ahead", x, re.I)
            and not (re.search(r"11/11", x) and any("month" in y.lower() for y in ctx[x.split(" [")[0].split(" notes")[0]]))]
    R.append(check("4 '11/11', '11 of 11', '408 ms' only with 'offline'", "FAIL" if bad else "PASS",
                   f"{len(bad)} line(s) without 'offline' (same line; check context by hand)", bad[:12]))

    # 5. per-point (stamp-calibrated) reading shown
    for grp, fl in (("paper", PAPER[:2]), ("video", VIDEO), ("deck", DECK)):
        h = hits(fl, r"stamp_calibrated|cv\.stc|stc_oos|same (clocks|inference)[^.]{0,60}per point|per point[^.]{0,40}los")
        R.append(check(f"5 per-point reading shown ({grp})", "PASS" if h else vfail(grp),
                       f"{len(h)} line(s)" + ("" if h or grp != "video" else f" ({KNOWN_NOTE})"), h[:3]))

    # 6. Dom's two questions each have a beat
    for grp, fl in (("paper", PAPER[:2]), ("video", VIDEO), ("deck", DECK)):
        e = hits(fl, r"results/e2e|e2e\.|frame.to.order|e2e_state|whole pipeline in milliseconds")
        c = hits(fl, r"results/capacity|capacity")
        R.append(check(f"6 Dom: latency proof + capacity ({grp})", "PASS" if e and c else vfail(grp),
                       f"e2e lines {len(e)}, capacity lines {len(c)}" + ("" if e and c or grp != "video" else
                       f" (the video's capacity line reads null; {KNOWN_NOTE})"), (e[:2] + c[:2])))
    # 6b the final video's capacity value is filled (it was rendered with capacity.json growth[...] = null)
    vm = ROOT / "results/viz/v60_assets/manifest.json"
    if vm.exists():
        vals = json.loads(vm.read_text()).get("values", {})
        nulls = [k for k in ("cap_lc_is", "cap_lc_oos") if k in vals and vals[k].get("shown") in (None, "")]
        R.append(check("6b capacity number on screen (video)", "KNOWN" if nulls else "PASS",
                       (f"{', '.join(nulls)} rendered null (on screen as '$pendingk'); {KNOWN_NOTE}" if nulls
                        else "filled"), ["results/viz/v60_assets/manifest.json::values"]))

    # 7. paper page budget
    aux = "\n".join(read("docs/paper/note.aux"))
    m = re.search(r"\\newlabel\{lastmain\}\{\{[^}]*\}\{(\d+)\}", aux)
    pg, src = (m.group(1), "docs/paper/note.aux") if m else (None, None)
    if pg is None and (ROOT / "results/paper/labels.json").exists():   # a clean clone has no note.aux (gitignored)
        lm = json.loads((ROOT / "results/paper/labels.json").read_text()).get("labels", {}).get("lastmain")
        pg, src = (lm[1], "results/paper/labels.json") if lm else (None, None)
    R.append(check("7 paper main text <= 5 pages", "PASS" if pg and int(pg) <= 5 else ("PENDING" if not pg else "FAIL"),
                   f"lastmain on page {pg or '?'} ({src or 'no label map'})"))

    # pending inputs
    e2e = ROOT / "results/e2e/summary.json"
    if e2e.exists():
        d = json.loads(e2e.read_text())
        need = ["our_pipeline_frame_to_order_ready_ms", "total_frame_to_executable_ms", "stage_ms", "label", "host",
                "budget_with_1s_simulated_feed"]
        miss = [k for k in need if k not in d]
        n = (d.get("our_pipeline_frame_to_order_ready_ms") or {}).get("n", 0)
        tot = (d.get("budget_with_1s_simulated_feed") or {}).get("total_ms", {})
        st = "PASS" if not miss and n >= 10 else "WARN"
        R.append(check("C7 e2e proof present (Dom 1)", st,
                       f"n = {n} order traces; ours p50 {d.get('our_pipeline_frame_to_order_ready_ms', {}).get('p50')} ms; "
                       f"total with 1 s simulated feed p50 {tot.get('p50')} ms vs 3,000 ms; host {d.get('host')}; "
                       f"missing keys {miss}; label '{d.get('label', '')[:60]}...'", ["results/e2e/summary.json"]))
    else:
        R.append(check("C7 e2e proof present (Dom 1)", "PENDING", "results/e2e/summary.json absent"))
    cap = ROOT / "results/capacity/capacity.json"
    if cap.exists():
        d = json.loads(cap.read_text())
        para = d.get("paragraph", "")
        lead_pre = bool(re.match(r".{0,200}pre-?registered", para, re.I | re.S))
        cal_bare = bool(re.search(r"calibrated(?![^.]{0,40}post hoc)", para, re.I))
        st = "PASS" if lead_pre and not cal_bare else "WARN"
        R.append(check("C8 capacity present (Dom 2)", st,
                       f"paragraph leads with the pre-registered reading: {lead_pre}; 'calibrated' without 'post hoc': "
                       f"{cal_bare}", ["results/capacity/capacity.json::paragraph"]))
    else:
        R.append(check("C8 capacity present (Dom 2)", "PENDING", "results/capacity/capacity.json absent"))
    nr = forward_not_run()
    for name, p, fwd in (("forward test (v2)", "results/v2/forward.json", True),
                         ("v2-safe forward (C9)", "results/v2/forward_safe.json", True),
                         ("tier-0 v3 forward", "results/tier0_v3/forward/results.json", True),
                         ("causal-CV cell (C5)", "results/redteam/causal_cv.json", False),
                         ("ex-ante replay filter (C1)", "results/replay/selective/selective.json", False)):
        if (ROOT / p).exists():
            R.append(check(f"input: {name}", "PASS", p))
        elif fwd and nr:
            R.append(check(f"input: {name}", "NOT RUN", f"pre-registered, not run within the hackathon window "
                                                          f"(HYPOTHESIS_V2.md {nr}); {p} absent by design"))
        else:
            R.append(check(f"input: {name}", "PENDING", p))
    live = ROOT / "results/live/summary.json"
    if live.exists():
        s = json.loads(live.read_text())
        R.append(check("input: live paper session", "PASS" if (ROOT / "results/live/FINAL").exists() else "PENDING",
                       f"status {s.get('status')!r}, now {s.get('now')!r}"))
    peeks = [x for x in read("results/oos_peeks.log") if x.strip()]
    R.append(check("peek log line count (quote this number)", "PASS", f"{len(peeks)} lines in results/oos_peeks.log"))
    try:
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "scripts/forward_test.py", "scripts/tier0_v3_forward.py",
                                "src/v2.py", "src/tiers.py", "src/fasttier.py", "research/v2/sizing/engine.py"],
                               cwd=ROOT, capture_output=True, text=True, timeout=30).stdout.strip()
        R.append(check("pinned forward pipeline unmodified", "FAIL" if dirty else "PASS", dirty or "clean vs HEAD"))
    except Exception as e:  # noqa: BLE001
        R.append(check("pinned forward pipeline unmodified", "WARN", f"git not available: {e}"))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"script": "scripts/redteam_acceptance.py", "checks": R}, indent=1))
    w = max(len(r["check"]) for r in R)
    for r in R:
        print(f"{r['status']:<8} {r['check']:<{w}}  {r['detail']}")
        for x in r["where"][:4]:
            print(f"{'':<9}{x}")
    n_fail = sum(r["status"] == "FAIL" for r in R)
    cnt = {k: sum(r["status"] == k for r in R) for k in ("WARN", "PENDING", "KNOWN", "NOT RUN")}
    print(f"\n{n_fail} FAIL, {cnt['WARN']} WARN, {cnt['PENDING']} PENDING, {cnt['KNOWN']} KNOWN (final video), "
          f"{cnt['NOT RUN']} NOT RUN (forward test, HYPOTHESIS_V2.md A5)")
    return 1 if (a.strict and n_fail) else 0


if __name__ == "__main__":
    sys.exit(main())
