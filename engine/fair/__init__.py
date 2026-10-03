"""Live fair value from the point-level Markov model (src.markov)."""
# Lazy exports (PEP 562) so `python -m engine.<pkg>.<module>` runs without a double import.
import importlib

_EXPORTS = {
    "CallEvent": "engine.fair.value",
    "FairJump": "engine.fair.value",
    "MatchFair": "engine.fair.value",
    "calibrate": "engine.fair.value",
    "call_winner": "engine.fair.value",
    "edge_after_fee": "engine.fair.value",
    "home_is_outcome0": "engine.fair.value",
    "parse_score": "engine.fair.value",
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    if name in _EXPORTS:
        return getattr(importlib.import_module(_EXPORTS[name]), name)
    raise AttributeError(name)
