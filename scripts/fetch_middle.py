"""Third crawler: starts mid-list so the three meet sooner."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.fetch_polymarket import MIN_VOL, SINCE, UNTIL  # noqa: E402
from src import polymarket as pm  # noqa: E402

ten = pm.enumerate_events("tennis", SINCE, UNTIL)
c = ten[ten.series.isin(["atp", "wta", "challenger"]) & (ten.volume >= MIN_VOL)].cond.tolist()
mid = len(c) // 2
pm.fetch_many_trades(c[mid:] + c[:mid])
