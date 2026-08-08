"""Position sizing — strategy-caems.md §Position sizing, implemented verbatim.

```
stop_fraction = |entry - stop| / entry
risk_notional = equity * risk_per_trade / stop_fraction
size = min(risk_notional, depth_cap, volume_cap, leverage_cap, exchange_cap)
```

`size` is a notional quote-currency amount throughout this module; callers divide by
entry price for a base-asset quantity.
"""

from __future__ import annotations

from dataclasses import dataclass

from scalping.config.settings import RiskConfig


class InvalidStopError(Exception):
    """Raised when entry == stop (division by zero in stop_fraction)."""


@dataclass(frozen=True)
class SizingInputs:
    equity: float
    entry: float
    stop: float
    available_depth: float
    bar_volume: float
    exchange_max_notional: float


@dataclass(frozen=True)
class SizingResult:
    size: float
    binding_cap: str


def compute_position_size(inputs: SizingInputs, risk: RiskConfig) -> SizingResult:
    stop_fraction = abs(inputs.entry - inputs.stop) / inputs.entry
    if stop_fraction <= 0:
        raise InvalidStopError("entry and stop must differ")

    risk_pct = (risk.risk_per_trade_pct / 100.0) * risk.risk_per_trade_multiplier
    risk_notional = inputs.equity * risk_pct / stop_fraction

    depth_cap = risk.depth_size_frac * inputs.available_depth
    volume_cap = risk.volume_cap_frac * inputs.bar_volume
    leverage_cap_notional = risk.leverage_cap * inputs.equity
    exchange_cap_notional = risk.exchange_cap_frac * inputs.exchange_max_notional

    candidates = {
        "risk_notional": risk_notional,
        "depth_cap": depth_cap,
        "volume_cap": volume_cap,
        "leverage_cap": leverage_cap_notional,
        "exchange_cap": exchange_cap_notional,
    }
    binding_cap = min(candidates, key=lambda k: candidates[k])
    return SizingResult(size=max(0.0, candidates[binding_cap]), binding_cap=binding_cap)
