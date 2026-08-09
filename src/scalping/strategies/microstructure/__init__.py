"""Microstructure strategy package (DOCS/strategy-microstructure-multiasset.md).

Import plugins from submodules to avoid circular imports with market_data.registry.
"""

from __future__ import annotations

__all__ = [
    "AltResidualStrategy",
    "CompressSmallStrategy",
    "EthLeadlagStrategy",
    "ListingOrStrategy",
    "OfiBtcStrategy",
    "PumpDefensiveStrategy",
    "SweepMidStrategy",
    "VShockStrategy",
    "all_microstructure_strategies",
]


def __getattr__(name: str):
    if name in __all__:
        from scalping.strategies.microstructure import plugins as _plugins

        return getattr(_plugins, name)
    raise AttributeError(name)
