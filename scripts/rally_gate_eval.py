"""Rally-in-progress gate: replay the live engine's held-out call log through engine/strategy.py's gate.

The live causal engine streamed the 7 held-out table-tennis videos (851 s, 120 fps, one NVIDIA L4) and emitted
172 CallEvents (results/engine/online_events_L4.jsonl: 160 BOUNCE, 12 MISS). Five MISS calls fell on labelled MISS
flights; seven fell on balls outside the 171 labelled flights (results/engine/online_vs_offline.json::
runs.*.calls). A trader would act on all 12. engine/strategy.py has a rally-state gate
(StrategyConfig.rally_gate_s): a MISS/OUT call is traded only if a BOUNCE/IN call on the same match came at most
rally_gate_s before it. This script measures what that gate does on the real log.

How (no engine file is edited; the gate is the real code path):
  * one CourtsideStrategy per gate value, StrategyConfig(rally_gate_s=g), paper only, no executor, no risk
    manager; each test video is one match;
  * every call is fed in the order the engine emitted it through CourtsideStrategy.on_call(match, call, t_ms),
    which records BOUNCE calls (note_call) and applies the gate (evaluate); a MISS whose decision reason is
    "no_rally_in_progress" was removed by the gate;
  * t_ms is the engine's emit time (t_emit, wall clock of the real-time run), which is what a live trader sees;
    the same replay on video time (frame / 120 fps) is reported as a check;
  * each MISS call is labelled with engine/vision/eval_online.assign_events (the matching behind
    online_vs_offline.json: same video and direction, frame within the labelled flight +/- 12 frames) against
    results/tracking/test_flights.csv, and calls outside the labelled flights are split into "between rallies"
    (outside the rally frame ranges) and "inside a rally range" with the flags stored in online_vs_offline.json.

Gate values: 0.5, 0.8 and 1.2 s (the sweep asked for), plus 2.0 s, the value the strategy's own comment fixes for any
live use before this evaluation. The labels are the held-out test labels, so this is a post hoc check on test data,
not a tuned rule; no gate value is chosen here.

Usage: .venv/bin/python scripts/rally_gate_eval.py   ->  results/engine/rally_gate_eval.json
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.strategy import CourtsideStrategy, StrategyConfig  # noqa: E402
from engine.vision.eval_online import assign_events  # noqa: E402

EVENTS = ROOT / "results/engine/online_events_L4.jsonl"
FLIGHTS = ROOT / "results/tracking/test_flights.csv"
ONLINE = ROOT / "results/engine/online_vs_offline.json"
OUT = ROOT / "results/engine/rally_gate_eval.json"
RUN_KEY = "fp16_cl_fuse_compile_b1_realtime"
FPS = 120.0
GATES = (0.5, 0.8, 1.2)
GATE_A_PRIORI = 2.0   # engine/strategy.py StrategyConfig.rally_gate_s comment: "2.0 s for any live use"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class _NoBook:
    has_snapshot = False


class _StubFeed:
    """The gate needs no market data; a call that passes it stops at 'no_book' (nothing is sent)."""

    def book(self, _token):
        return _NoBook()

    def now_ms(self):
        raise RuntimeError("every call carries its own t_ms")


def replay(events: list[dict], gate_s: float, clock: str) -> dict[tuple, dict]:
    """(video, frame, call) -> {reason, gap_ms} for every MISS call, through CourtsideStrategy.on_call."""
    st = CourtsideStrategy(_StubFeed(), None, None, StrategyConfig(rally_gate_s=gate_s))
    for v in sorted({e["video"] for e in events}):
        st.add_match(v, f"{v}_A", f"{v}_B", calibrate=False)
    key = (lambda e: e["t_emit"]) if clock == "emit" else (lambda e: e["frame"] / FPS)
    out, last_b = {}, {}
    for e in sorted(events, key=lambda e: (e["video"], key(e), e["frame"])):
        t_ms = int(round(key(e) * 1000.0))
        ev = SimpleNamespace(call=e["call"], frame=e["frame"], p_miss=e["p_miss"], direction=e["direction"],
                             lead_ms=e["lead_ms"], latency_ms=e["latency_ms"])
        d = st.on_call(e["video"], ev, t_ms=t_ms)
        if e["call"] == "MISS":
            lb = last_b.get(e["video"])
            out[(e["video"], e["frame"], e["call"])] = dict(reason=d.reason, gap_ms=None if lb is None else t_ms - lb)
        else:
            last_b[e["video"]] = t_ms
    return out


def main() -> int:
    events = [json.loads(l) for l in EVENTS.read_text().splitlines() if l.strip()]
    fl = pd.read_csv(FLIGHTS)
    first_miss, _first_bounce, unmatched, matched = assign_events(events, fl)
    ov = json.loads(ONLINE.read_text())
    calls_ref = ov["runs"][RUN_KEY]["calls"]
    in_range = {(u["video"], u["frame"]): u["inside_rally_range"] for u in calls_ref["unmatched"]["first"]
                if u["call"] == "MISS"}
    video_s = float(ov["runs"][RUN_KEY]["timing"]["video_seconds"])

    # label every MISS call
    lab = {}
    first_ids = {id(e) for e in first_miss.values()}
    for fid, e in matched:
        if e["call"] != "MISS":
            continue
        y = fl.label[fid]
        if y == "MISS" and id(e) in first_ids:
            cls = "correct_early" if e["frame"] <= fl.t_ref[fid] else "correct_after_T_ref"
        elif y == "MISS":
            cls = "repeat_on_MISS_flight"
        else:
            cls = "wrong_on_BOUNCE_flight"
        lab[(e["video"], e["frame"], "MISS")] = dict(cls=cls, flight=int(fid), t_ref=int(fl.t_ref[fid]))
    for e in unmatched:
        if e["call"] == "MISS":
            r = in_range.get((e["video"], e["frame"]))
            lab[(e["video"], e["frame"], "MISS")] = dict(
                cls="outside_flights_between_rallies" if r is False else "outside_flights_inside_rally_range",
                flight=None, t_ref=None)
    n_miss = sum(e["call"] == "MISS" for e in events)
    assert len(lab) == n_miss == 12, (len(lab), n_miss)
    cnt = lambda pred: sum(1 for v in lab.values() if pred(v["cls"]))
    correct = lambda c: c.startswith("correct")
    outside = lambda c: c.startswith("outside")
    between = lambda c: c == "outside_flights_between_rallies"
    # the labelling must reproduce the committed counts
    assert cnt(correct) == calls_ref["miss_calls_on_MISS_flights"] == 5
    assert cnt(lambda c: c == "correct_after_T_ref") == calls_ref["miss_calls_after_T_ref"] == 1
    assert cnt(lambda c: c == "wrong_on_BOUNCE_flight") == calls_ref["miss_calls_on_BOUNCE_flights"] == 0
    assert cnt(outside) == calls_ref["unmatched"]["MISS"] == 7
    assert cnt(between) == calls_ref["unmatched"]["MISS_outside_rally_ranges"] == 5

    res = {}
    table = {k: dict(video=k[0], frame=k[1], media_t_s=round(k[1] / FPS, 3), label=v["cls"],
                     labelled_flight=v["flight"], t_ref=v["t_ref"]) for k, v in lab.items()}
    for clock in ("emit", "video"):
        res[clock] = {}
        for g in (*GATES, GATE_A_PRIORI):
            r = replay(events, g, clock)
            assert set(r) == set(lab)
            kept = {k for k, d in r.items() if d["reason"] != "no_rally_in_progress"}
            stale = [k for k, d in r.items() if d["reason"] == "stale_call"]
            row = dict(
                gate_s=g,
                a_priori=(g == GATE_A_PRIORI),
                miss_calls=len(r),
                kept=len(kept),
                correct_kept=sum(1 for k in kept if correct(lab[k]["cls"])),
                correct_total=cnt(correct),
                correct_early_kept=sum(1 for k in kept if lab[k]["cls"] == "correct_early"),
                correct_early_total=cnt(lambda c: c == "correct_early"),
                correct_lost=sorted([dict(video=k[0], frame=k[1], label=lab[k]["cls"],
                                          gap_since_last_bounce_ms=r[k]["gap_ms"])
                                     for k in r if k not in kept and correct(lab[k]["cls"])],
                                    key=lambda x: (x["video"], x["frame"])),
                outside_flights_removed=sum(1 for k in r if k not in kept and outside(lab[k]["cls"])),
                outside_flights_total=cnt(outside),
                between_rallies_removed=sum(1 for k in r if k not in kept and between(lab[k]["cls"])),
                between_rallies_total=cnt(between),
                stale_call_skips=len(stale),
                outside_flights_per_hour_ungated=round(cnt(outside) / video_s * 3600.0, 1),
                outside_flights_per_hour_gated=round(
                    sum(1 for k in kept if outside(lab[k]["cls"])) / video_s * 3600.0, 1),
            )
            res[clock][f"{g:g}"] = row
            for k in r:
                table[k].setdefault(f"gap_since_last_bounce_ms_{clock}", r[k]["gap_ms"])
                table[k][f"kept_{clock}_{g:g}s"] = k in kept

    out = dict(
        what=("Rally-in-progress gate (engine/strategy.py StrategyConfig.rally_gate_s) replayed on the live engine's "
              "held-out table-tennis call log; paper only, post hoc on test labels, no gate value chosen here"),
        script="scripts/rally_gate_eval.py",
        generated_utc=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        inputs={str(p.relative_to(ROOT)): sha(p) for p in (EVENTS, FLIGHTS, ONLINE, ROOT / "engine/strategy.py")},
        definitions=dict(
            gate="a MISS call trades only if a BOUNCE call on the same match came 0 to gate_s before it "
                 "(CourtsideStrategy.evaluate, reason 'no_rally_in_progress' otherwise)",
            correct="the first MISS call on a labelled MISS flight (engine/vision/eval_online.assign_events); "
                    "correct_early: at or before T_ref",
            outside_flights="a MISS call on a ball outside the 171 labelled flights (wrong for trading: no point "
                            "ended there); between_rallies: outside the rally frame ranges as flagged in "
                            "online_vs_offline.json, the rest inside a rally range (serve tosses, rally-ending balls)",
            clocks="emit: t_emit, the engine's emit wall clock in the real-time run (what a live trader sees); "
                   "video: frame / 120 fps",
            a_priori=f"{GATE_A_PRIORI:g} s is the value the engine/strategy.py comment sets for any live use; "
                     "0.5, 0.8 and 1.2 s are the sensitivity sweep"),
        counts=dict(video_seconds=video_s, events=len(events), bounce_calls=len(events) - n_miss, miss_calls=n_miss,
                    correct=cnt(correct), correct_early=cnt(lambda c: c == "correct_early"),
                    outside_flights=cnt(outside), between_rallies=cnt(between),
                    wrong_on_bounce_flights=cnt(lambda c: c == "wrong_on_BOUNCE_flight")),
        results=res,
        miss_calls=sorted(table.values(), key=lambda x: (x["video"], x["frame"])),
        limits="7 videos, 12 MISS calls: counts, not rates. Table tennis only; tennis would need a serve detector "
               "for the same gate. The labels are the held-out test labels, read after the run.",
    )
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    for clock in res:
        for g, row in res[clock].items():
            print(f"{clock:5s} gate {g:>3s}s: kept {row['kept']}/12; correct kept {row['correct_kept']}/"
                  f"{row['correct_total']} (early {row['correct_early_kept']}/{row['correct_early_total']}); "
                  f"outside removed {row['outside_flights_removed']}/{row['outside_flights_total']} "
                  f"(between rallies {row['between_rallies_removed']}/{row['between_rallies_total']})")
    print(f"-> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
