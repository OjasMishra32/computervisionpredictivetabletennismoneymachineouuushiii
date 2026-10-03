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

G, R, Y, B, D, X, BOLD = "\033[32m", "\033[31m", "\033[33m", "\033[36m", "\033[2m", "\033[0m", "\033[1m"


def money(v: float) -> str:
    return f"{G if v >= 0 else R}{'+' if v >= 0 else '−'}${abs(v):,.2f}{X}"


def main(speed: float, every: int):
    u = universe()
    title = u.set_index("cond").title.to_dict()
    oos = set(u.loc[u.oos, "cond"])
    oos_start = u.loc[u.oos, "start"].min().timestamp()
    tr = pd.read_parquet("data/v2_trades_is_oos.parquet")
    tr = tr[tr.month >= "2026-02"].sort_values("ts").reset_index(drop=True)
    tr["day"] = pd.to_datetime(tr.ts, unit="s").dt.floor("D")
    print(f"{BOLD}{B}COURTSIDE v2 · backtest replay{X}  {len(tr):,} real fills · {tr.day.nunique()} days · paper money, real Polymarket data")
    print(f"{D}fast-tier window measured from jump detection · risk-parity size · ≤100 shares net per match · held to the match result · net of each match's fee{X}\n")
    total, peak, mdd, wins, n = 0.0, 0.0, 0.0, 0, 0
    daily, crossed = [], False
    for day, g in tr.groupby("day", sort=True):
        if not crossed and g.ts.min() >= oos_start:
            crossed = True
            print(f"\n{BOLD}{Y}══════ OUT OF SAMPLE from here (matches from 2026-08-25, locked until the rules were frozen) ══════{X}\n")
        day_pnl = 0.0
        for i, r in enumerate(g.itertuples()):
            total += r.pnl; day_pnl += r.pnl; n += 1; wins += r.pnl > 0
            peak = max(peak, total); mdd = min(mdd, total - peak)
            if i % every == 0:
                side = "BUY " + ("A" if r.dir > 0 else "B")
                name = (title.get(r.cond, r.cond[:10]) or "")[:44]
                print(f"{D}{pd.to_datetime(r.ts, unit='s'):%m-%d %H:%M:%S}{X}  {name:44} {side} {r.shares:7.1f} sh @ {r.q*100:5.1f}¢  "
                      f"→ {money(r.pnl):>18}   {BOLD}BOOK {money(total)}{X}")
        daily.append(day_pnl)
        d = np.array(daily)
        sharpe = d.mean() / d.std() * np.sqrt(365) if len(d) > 2 and d.std() > 0 else float("nan")
        tag = "OOS" if crossed else "IS "
        print(f"{BOLD}── {day:%Y-%m-%d} [{tag}]  day {money(day_pnl)}  ·  book {money(total)}  ·  {n:,} fills  ·  win {100*wins/n:4.1f}%  ·  "
              f"profitable days {100*(d>0).mean():4.1f}%  ·  Sharpe {sharpe:5.1f}  ·  max DD {money(mdd)} ──{X}")
        time.sleep(1.0 / speed)
    print(f"\n{BOLD}FINAL  book {money(total)}  ·  {n:,} fills  ·  max drawdown {money(mdd)}{X}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--speed", type=float, default=2.0, help="simulated days per second")
    ap.add_argument("--every", type=int, default=25, help="print every Nth fill (the counter includes all of them)")
    a = ap.parse_args()
    try:
        main(a.speed, a.every)
    except KeyboardInterrupt:
        pass
