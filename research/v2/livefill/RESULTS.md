# Live passive-exit fill study (forward data, 2026-10-03)

`python research/v2/livefill/livefill.py` streams today's recorded tennis order books (data/live/).
After each live moneyline jump (mid +3¢ within 10 s; 393 jumps on 45 tokens, 10:03–12:21 UTC) we hold the token that
gained from jump + 1 s and rest a sell, either 1 tick inside the ask (alone at the level) or at the
ask behind the visible queue (median 238 shares). It fills when takers trade through our price on
this token or its twin.

| mode | fill ≤30 s | ≤60 s | ≤120 s | ≤300 s | mid 30 s after fill vs our price | mid drift 300 s, unfilled |
|---|---|---|---|---|---|---|
| 1 tick inside | 27% | 35% | 43% | 56% | +5.6¢ (price kept rising) | −5.7¢ |
| join queue | 14% | 21% | 28% | 37% | +7.4¢ | −1.9¢ |

Passive exits are adversely selected. They fill when the price keeps running (we sold too early) and
fail to fill when it reverses (we keep the loser). A tape-based exit model that fills at the first
later print through our price cannot see this. Do not use a maker exit as the primary P&L assumption.
