#!/usr/bin/env python
"""Extra data for the match-replay visuals (figures and demo video). Descriptive only: no parameter is chosen.

    BACKTEST REPLAY on a real match recorded live on 2026-10-03 — assumed 1 s licensed video feed (not
    purchased); bounce time = official point stamp - assumed stamp lag; fills priced against the real
    recorded order book; paper only.

No video of any match was received, bought or watched. This script re-reads the same live recording as
scripts/match_replay.py, with the same functions and the same frozen settings, and writes:

  results/replay/selected_match_tob_events.csv.gz  every top-of-book change of the selected match (both
                                                   tokens, best bid / ask and best-ask size), server clock,
                                                   from 10 s before its first official point to 40 s after
                                                   its last; the 250 ms grid in selected_match_book.csv is a
                                                   sample of this
  results/replay/selected_match_trades.csv         every recorded print (last_trade_price) of that market
  results/replay/seed_fills.csv                    every fill of seeds 0-19 at V = 0 / 0.5 / 1.0 s (stamp lag
                                                   2.0 s, model lead, Florida 67 ms) with its execution time and
                                                   P&L, for the cumulative P&L bands

Checks (the run fails if they do not hold): seed 0 reproduces results/replay/points.csv fill by fill and every
seed reproduces results/replay/seed_robustness.csv; the event-level book agrees with the 250 ms grid and with
the ask at execution recorded in points.csv.

    .venv/bin/python scripts/match_replay_extras.py --cache /path/outside/repo/parsed.pkl
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import match_replay as MR  # noqa: E402

OUT = MR.OUT


def tob_events(rows: list, t0: int, t1: int) -> pd.DataFrame:
    """Top of book of both tokens after every event (effective server time) in [t0, t1]; the first row is the
    state at t0. Consecutive identical states are dropped."""
    bids, asks = [{}, {}], [{}, {}]
    out = []
    last = None

    def state():
        bb0 = max(bids[0]) if bids[0] else np.nan
        ba0 = min(asks[0]) if asks[0] else np.nan
        bb1 = max(bids[1]) if bids[1] else np.nan
        ba1 = min(asks[1]) if asks[1] else np.nan
        s0 = asks[0].get(ba0, np.nan) if asks[0] else np.nan
        s1 = asks[1].get(ba1, np.nan) if asks[1] else np.nan
        return (bb0, ba0, bb1, ba1, s0, s1)

    started = False
    for eff, _, k, d in rows:
        if eff > t1:
            break
        if eff >= t0 and not started:
            st = state()
            out.append((t0, *st))
            last = st
            started = True
        if k == 0:
            for tok, is_bid, p, sz in d:
                side = bids[tok] if is_bid else asks[tok]
                if sz > 0:
                    side[p] = sz
                else:
                    side.pop(p, None)
        elif k == 1:
            tok, b, a = d
            bids[tok] = {p: s for p, s in b if s > 0}
            asks[tok] = {p: s for p, s in a if s > 0}
        else:
            continue
        if eff >= t0:
            st = state()
            if st != last:
                out.append((eff, *st))
                last = st
    df = pd.DataFrame(out, columns=["t_ms", "bid0", "ask0", "bid1", "ask1", "asksz0", "asksz1"])
    # several events at the same millisecond: keep the state after the last of them
    return df.drop_duplicates("t_ms", keep="last").reset_index(drop=True)


def main(cache: str | None) -> None:
    res = json.loads((OUT / "replay.json").read_text())
    P, M = MR.load_points()
    sel = M[M.selected].iloc[0]
    assert sel.slug == res["selected_match"]
    print("parsing the recording ...")
    R = MR.parse_recording(M, cache)
    lat = np.array(R["recv_latency_ms"])
    l_recv = int(round(float(np.median(lat))))
    assert l_recv == res["model"]["recv_latency_ms_median"], (l_recv, res["model"]["recv_latency_ms_median"])
    rows = {c: MR.effective_events(e, l_recv) for c, e in R["events"].items()}
    winners = {}
    for c, e in R["events"].items():
        w = [d for _, _, k, d in e if k == 3]
        winners[c] = w[-1] if w else None

    # ------------------------------------------------------------ seeds 0-19, headline settings, V = 0 / 0.5 / 1
    from src import tier0
    cvd = tier0.cv_systems()["own120"]
    p_out = tier0.point_mix()["women"]["out"]
    plan = []
    for seed in MR.SEEDS:
        dr = MR.draws(len(P), seed)
        lead = MR.leads_ms(dr, cvd, p_out)
        for V in MR.VS:
            plan.append((seed, V, dr, lead, MR.cell_times(P, lead, MR.HEADLINE["lag"], V, MR.NETS[MR.HEADLINE["net"]])))
    cond_of = P.slug.map(dict(zip(M.slug, M.cond))).to_numpy()
    need = {c: set() for c in M.cond}
    for *_, tm in plan:
        for k in ("t_ref", "exec", "mark"):
            for c, t in zip(cond_of, tm[k]):
                need[c].add(int(t))
    print(f"capturing books at {sum(len(v) for v in need.values()):,} instants ...")
    snaps = {c: MR.capture(rows[c], np.array(sorted(need[c]), dtype=np.int64)) for c in M.cond}
    pts = pd.read_csv(OUT / "points.csv")
    sr = pd.read_csv(OUT / "seed_robustness.csv")
    fills = []
    for seed, V, dr, lead, tm in plan:
        cell = {"V": V, "lag": MR.HEADLINE["lag"], "lead": MR.HEADLINE["lead"], "net": MR.HEADLINE["net"], "seed": seed}
        D = MR.simulate(P, M, snaps, tm, dr, lead, winners, l_recv, cell)
        s = MR.stats(D, ci=False)
        ref = sr[(sr.seed == seed) & (sr.V == V)].iloc[0]
        assert abs(s["pnl_mark_usd"] - ref.pnl_mark_usd) < 1e-2 and s["fills"] == ref.fills, (seed, V)
        if seed == 0:       # fill-by-fill against points.csv
            a = D[D.shares > 1e-9].sort_values(["slug", "n"])
            b = pts[(pts.V == V) & (pts.shares > 1e-9)].sort_values(["slug", "n"])
            assert len(a) == len(b) and np.allclose(a.shares.to_numpy(), b.shares.to_numpy(), atol=1e-3)
            assert np.allclose(a.pnl_mark.fillna(0).to_numpy(), b.pnl_mark.fillna(0).to_numpy(), atol=1e-3)
        F = D[D.shares > 1e-9]
        for r in F.itertuples():
            fills.append({"seed": seed, "V": V, "slug": r.slug, "n": r.n, "exec_ms": r.exec_ms,
                          "correct_call": bool(r.correct_call), "beat_book": r.beat_book, "shares": r.shares,
                          "vwap": r.vwap, "pnl_mark": r.pnl_mark, "pnl_hold": r.pnl_hold})
    SF = pd.DataFrame(fills)
    with open(OUT / "seed_fills.csv", "w") as f:      # label in a comment header (pandas: comment="#")
        f.write(f"# {MR.LABEL}\n# fills of seeds 0-19, stamp lag 2.0 s, model lead, Florida 67 ms; exec_ms = UTC ms\n")
        SF.to_csv(f, index=False, float_format="%.6g")
    print(f"seed_fills.csv: {len(SF):,} fills over {SF.seed.nunique()} seeds (seed totals match seed_robustness.csv)")

    # ------------------------------------------------------------ event-level book + prints of the selected match
    g = pts[(pts.slug == sel.slug) & (pts.V == 1.0)]
    t0 = int(g.T_ms.min()) - 10_000 - 2_000
    t1 = int(g.T_ms.max()) + 40_000
    E = tob_events(rows[sel.cond], t0, t1)
    tl = pd.read_csv(OUT / "selected_match_book.csv", comment="#")
    tl = tl[(tl.t_ms >= t0) & (tl.t_ms <= t1)]
    idx = np.searchsorted(E.t_ms.to_numpy(), tl.t_ms.to_numpy(), side="right") - 1
    ok = np.isclose(E.ask0.to_numpy()[idx], tl.ask0.to_numpy(), equal_nan=True)
    assert ok.mean() > 0.999, ok.mean()
    sp = pts[(pts.slug == sel.slug) & pts.ask_at_exec.notna()]
    i2 = np.searchsorted(E.t_ms.to_numpy(), sp.exec_ms.to_numpy(), side="right") - 1
    called0 = (sp.called_player == sel.n0).to_numpy()
    ask_e = np.where(called0, E.ask0.to_numpy()[i2], E.ask1.to_numpy()[i2])
    assert np.allclose(ask_e, sp.ask_at_exec.to_numpy()), "event book disagrees with ask_at_exec"
    with gzip.open(OUT / "selected_match_tob_events.csv.gz", "wt") as f:
        f.write(f"# {MR.LABEL}\n# {sel.slug}: outcome 0 = {sel.n0}, outcome 1 = {sel.n1}; every top-of-book "
                f"change (state after the event), effective server clock UTC ms (book snapshots at rt - {l_recv} ms)\n")
        E.to_csv(f, index=False, float_format="%.6g")
    print(f"selected_match_tob_events.csv.gz: {len(E):,} book states; agrees with the 250 ms grid at "
          f"{ok.mean():.2%} of grid instants and with ask_at_exec at all {len(sp)} orders")
    T = []
    for eff, _, k, d in rows[sel.cond]:
        if k == 2 and t0 <= eff <= t1:
            tok, px, sz, side = d
            T.append((eff, tok, px, sz, side))
    TR = pd.DataFrame(T, columns=["t_ms", "token", "price", "size", "side"])
    with open(OUT / "selected_match_trades.csv", "w") as f:
        f.write(f"# {MR.LABEL}\n# {sel.slug}: recorded last_trade_price prints, server clock UTC ms; token 0 = "
                f"{sel.n0}, token 1 = {sel.n1}\n")
        TR.to_csv(f, index=False, float_format="%.6g")
    print(f"selected_match_trades.csv: {len(TR):,} prints")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=None, help="pickle of the parsed recording (keep it outside the repo)")
    main(ap.parse_args().cache)
