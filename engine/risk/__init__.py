"""Pre-trade risk: v2 limits, daily stop, kill switches."""
# Lazy exports (PEP 562) so `python -m engine.<pkg>.<module>` runs without a double import.
import importlib

_EXPORTS = {
    "V2_K": "engine.risk.limits",
    "V2_MAX_ORDER_USD": "engine.risk.limits",
    "V2_NET_CAP_SHARES": "engine.risk.limits",
    "V2_ZONE": "engine.risk.limits",
    "Approval": "engine.risk.limits",
    "RiskConfig": "engine.risk.limits",
    "RiskManager": "engine.risk.limits",
    "risk_parity_shares": "engine.risk.limits",
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    if name in _EXPORTS:
        return getattr(importlib.import_module(_EXPORTS[name]), name)
    raise AttributeError(name)
