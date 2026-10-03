"""CallEvent: what every vision call source emits, and the paper-only guard.

The vision engine produces calls; it never trades. Anything that consumes CallEvents in this repo
simulates execution against live or recorded books (src/paper.py). The guard below makes that
explicit: importing or constructing an engine raises if live trading is switched on anywhere in the
environment, and `enable_live_trading` always raises.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field

PAPER_ONLY = True
# keep in sync with engine/execution/paper.py LIVE_ENV_FLAGS (not imported: the vision engine runs standalone)
_LIVE_FLAGS = ("COURTSIDE_LIVE_TRADING", "LIVE_TRADING", "ENABLE_LIVE_TRADING", "POLYMARKET_PRIVATE_KEY",
               "PRIVATE_KEY", "PK", "WALLET_PRIVATE_KEY", "POLY_PRIVATE_KEY", "CLOB_API_KEY", "CLOB_SECRET",
               "CLOB_PASS_PHRASE", "CLOB_API_SECRET", "CLOB_API_PASSPHRASE", "POLY_API_KEY", "POLY_SECRET",
               "POLY_PASSPHRASE")


class LiveTradingForbidden(RuntimeError):
    """Raised whenever anything tries to enable live order placement from the vision engine."""


def assert_paper_only() -> None:
    """Raise if the environment asks for live trading or carries wallet / order credentials."""
    if not PAPER_ONLY:
        raise LiveTradingForbidden("PAPER_ONLY was modified; the vision engine is paper only")
    bad = [k for k in _LIVE_FLAGS if os.environ.get(k, "").strip() not in ("", "0", "false", "False")]
    if bad:
        raise LiveTradingForbidden(
            f"live-trading / credential variables set: {bad}. The vision engine is paper only: it never "
            "loads keys, signs, sends or places orders. Unset them.")


def enable_live_trading(*_a, **_k):
    raise LiveTradingForbidden("live trading is disabled in COURTSIDE (paper only, by design)")


assert_paper_only()


@dataclass
class CallEvent:
    """One call. Times: t_frame and t_emit are wall clock (time.time(), seconds).

    t_frame   when the decision frame became available to the engine (capture / arrival time)
    t_emit    when the event was emitted (after detection, tracking, features, classifier)
    call      "MISS" (point ends: out / net) or "BOUNCE" (ball lands in, rally goes on)
    p_miss    frozen classifier score at the decision frame (0 while the horizon gate is closed)
    lead_ms   predicted time from the decision frame to contact (net plane / end line / table)
    frame     decision frame index in source numbering (frame_offset applied)
    """
    call: str
    frame: int
    t_frame: float
    t_emit: float
    p_miss: float
    lead_ms: float
    source: str = "table_tennis"
    rule: str = ""
    media_t: float = float("nan")
    flight_t0: int = -1
    direction: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def latency_ms(self) -> float:
        return (self.t_emit - self.t_frame) * 1000.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["latency_ms"] = self.latency_ms
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=float)


def now() -> float:
    return time.time()
