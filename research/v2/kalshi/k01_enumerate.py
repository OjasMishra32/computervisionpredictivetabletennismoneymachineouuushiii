"""Step 1: enumerate settled IS Kalshi ATP/WTA match-winner markets (cached)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import kalshi_api as ka

if __name__ == "__main__":
    print("cutoff", ka.cutoff())
    for s in ["KXATPMATCH", "KXWTAMATCH"]:
        m = ka.list_markets(s)
        print(s, len(m), "markets", m.event_ticker.nunique(), "events",
              m.close_time.min(), m.close_time.max(), m.tier.value_counts().to_dict())
