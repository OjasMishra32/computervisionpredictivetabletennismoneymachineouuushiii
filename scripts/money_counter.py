"""Replay the v2 backtest in the terminal with a running money counter (paper money, real data).

    .venv/bin/python scripts/money_counter.py              # ~2 simulated days per second
    .venv/bin/python scripts/money_counter.py --speed 10   # faster

Every line is a real historical fill from the v2 (causal) backtest: Polymarket price, our size, the
match's real result and fee. P&L is booked at entry for display; positions are held to the result.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.tape import universe  # noqa: E402

START_CAPITAL = 28_300  # v2 in-sample capital: 3x peak locked (results/v2/causal.json)
G, R, Y, B, D, X, BOLD = "\033[32m", "\033[31m", "\033[33m", "\033[36m", "\033[2m", "\033[0m", "\033[1m"


def money(v: float) -> str:
    return f"{G if v >= 0 else R}{'+' if v >= 0 else '−'}${abs(v):,.2f}{X}"


def summary(lbl: str, start_cap: float, pnl: float, days: list, n: int, wins: int, mdd: float) -> str:
    d = np.array(days) if days else np.zeros(1)
    sh = d.mean() / d.std() * np.sqrt(365) if len(d) > 2 and d.std() > 0 else float("nan")
    return (f"{BOLD}{lbl:<16} start ${start_cap:,.0f} → ${start_cap + pnl:,.0f}  ({money(pnl)}{BOLD}, {100*pnl/start_cap:+.1f}%)  ·  "
            f"{len(d)} days · {n:,} fills · win {100*wins/max(n,1):.1f}% · profitable days {100*(d>0).mean():.0f}% · "
            f"Sharpe {sh:.1f} · max DD {money(mdd)}{X}")


def main(speed: float, every: int):
    u = universe()
    title = u.set_index("cond").title.to_dict()
    oos_start = u.loc[u.oos, "start"].min().timestamp()
    oos_conds = set(u.loc[u.oos, "cond"])
    tr = pd.read_parquet("data/v2_trades_is_oos.parquet")
    tr = tr[tr.month >= "2026-02"].sort_values("ts").reset_index(drop=True)
    tr["day"] = pd.to_datetime(tr.ts, unit="s").dt.floor("D")
    tr["oos"] = tr.cond.isin(oos_conds)
    cap = START_CAPITAL
    print(f"{BOLD}{B}COURTSIDE v2 · backtest replay{X}  paper money, real Polymarket fills, net of fees, held to each match's result")
    print(f"{BOLD}Starting account: ${cap:,.0f}{X} {D}(3x the most money ever tied up in open positions, so it never runs short){X}\n")
    stats = {}
    for period, part in (("IN SAMPLE", tr[~tr.oos]), ("OUT OF SAMPLE", tr[tr.oos])):
        if period == "OUT OF SAMPLE":
            print(f"\n{BOLD}{Y}══════ OUT OF SAMPLE: matches from 2026-08-25, locked until the rules were frozen. Tally restarts at $0 ══════{X}\n")
        total = peak = mdd = 0.0; wins = n = 0; daily = []
        for day, g in part.groupby("day", sort=True):
            day_pnl = 0.0
            for i, r in enumerate(g.itertuples()):
                total += r.pnl; day_pnl += r.pnl; n += 1; wins += r.pnl > 0
                peak = max(peak, total); mdd = min(mdd, total - peak)
                if i % every == 0:
                    name = (title.get(r.cond, r.cond[:10]) or "")[:42]
                    print(f"{D}{pd.to_datetime(r.ts, unit='s'):%m-%d %H:%M:%S}{X}  {name:42} BUY {'A' if r.dir > 0 else 'B'} {r.shares:6.1f} sh @ {r.q*100:5.1f}¢ "
                          f"→ {money(r.pnl):>17}")
            daily.append(day_pnl)
            print(f"{BOLD}── {day:%Y-%m-%d} [{period}]  day {money(day_pnl)}  ·  account ${cap + total:,.0f} ({100*total/cap:+.1f}%)  ·  "
                  f"profitable days {100*np.mean(np.array(daily) > 0):.0f}%  ·  max DD {money(mdd)} ──{X}")
            time.sleep(1.0 / speed)
        stats[period] = (total, daily, n, wins, mdd)
        print("\n" + summary(period, cap, total, daily, n, wins, mdd))
    print(f"\n{BOLD}{B}SCORECARD (same ${cap:,.0f} account, each period scored on its own){X}")
    for k, (t, d, n, w, m) in stats.items():
        print("  " + summary(k, cap, t, d, n, w, m))
    print(f"{D}Paper book at the fast tier's own fill prices (see docs/NOTE.pdf, Table 2 for slippage).{X}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--speed", type=float, default=2.0, help="simulated days per second")
    ap.add_argument("--every", type=int, default=25, help="print every Nth fill (the counter includes all of them)")
    a = ap.parse_args()
    try:
        main(a.speed, a.every)
    except KeyboardInterrupt:
        pass
