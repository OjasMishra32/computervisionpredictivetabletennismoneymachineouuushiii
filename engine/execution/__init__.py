"""Paper execution only: simulated taker fills against live or recorded books. Never sends orders."""
# Lazy exports (PEP 562) so `python -m engine.<pkg>.<module>` runs without a double import.
import importlib

_EXPORTS = {
    "PAPER_ONLY": "engine.execution.paper",
    "VENUE_DELAY_MS": "engine.execution.paper",
    "Decision": "engine.execution.paper",
    "Ledger": "engine.execution.paper",
    "LiveTradingForbidden": "engine.execution.paper",
    "PaperExecutor": "engine.execution.paper",
    "PaperFill": "engine.execution.paper",
    "PaperOrder": "engine.execution.paper",
    "assert_paper": "engine.execution.paper",
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    if name in _EXPORTS:
        return getattr(importlib.import_module(_EXPORTS[name]), name)
    raise AttributeError(name)
