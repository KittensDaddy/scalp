"""Deprecated stub module — real strategies live in plugins.py."""

from scalping.strategies.microstructure.plugins import all_microstructure_strategies


def all_stubs():
    """Historical name; returns live microstructure plugins (not DATA_UNAVAILABLE stubs)."""
    return [p for p in all_microstructure_strategies() if p.strategy_id != "ALT_RESIDUAL"]
