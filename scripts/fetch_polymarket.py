"""Step 1: crawl every resolved Polymarket tennis / table-tennis moneyline and its trade tape."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import polymarket as pm  # noqa: E402

SINCE, UNTIL = "2025-07-01", "2026-10-03"
MIN_VOL = 5_000  # tapes below this are too thin to say anything about

if __name__ == "__main__":
    for tag in ("tennis", "table-tennis"):
        df = pm.enumerate_events(tag, SINCE, UNTIL)
        print(tag, len(df), "moneylines; volume", round(df.volume.sum()), flush=True)
    ten = pm.enumerate_events("tennis", SINCE, UNTIL)
    singles = ten[ten.series.isin(["atp", "wta", "challenger"]) & (ten.volume >= MIN_VOL)]
    print("fetching tapes for", len(singles), "singles matches", flush=True)
    pm.fetch_many_trades(singles.cond.tolist())
