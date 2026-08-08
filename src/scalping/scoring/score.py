"""Setup Score — SCANNER_DASHBOARD_PLAN.md §E: deterministic 0-100, not a
probability. `score = clamp(sum(component_i), 0, 100)`, weights in config, every
component logged with the signal.

Deliberately pure: takes only already-computed `ScoreInputs` plus a timestamp the
caller supplies (`evaluated_at`) — "no wall-clock reads inside" is what makes this
replay-deterministic (SCANNER_DASHBOARD_PLAN.md §E). Turning raw indicator state
into `ScoreInputs` is `scoring/features.py`'s job, not this module's.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ScoreWeights:
    trend_alignment_max: float = 18.0
    momentum_max: float = 16.0
    relative_volume_max: float = 14.0
    entry_quality_max: float = 13.0
    historical_edge_max: float = 12.0
    liquidity_max: float = 10.0
    volatility_regime_max: float = 8.0
    confirmations_max: float = 4.0
    spread_penalty_max: float = 8.0
    slippage_penalty_max: float = 5.0


@dataclass(frozen=True)
class ScoreInputs:
    """Every `*_frac` field is in [0, 1]: for positive components, how fully the
    component is satisfied; for the two penalty fields, how severe the penalty is
    (0 = none, 1 = maximum). `stale` is categorical, not graduated — per
    SCANNER_DASHBOARD_PLAN.md §E "staleness_penalty ... nukes the score", any stale
    read zeroes the total outright rather than subtracting a graduated amount.
    """

    trend_alignment_frac: float
    momentum_frac: float
    relative_volume_frac: float
    entry_quality_frac: float
    historical_edge_frac: float
    liquidity_frac: float
    volatility_regime_frac: float
    confirmations_frac: float
    spread_penalty_frac: float
    slippage_penalty_frac: float
    stale: bool
    evaluated_at: datetime


@dataclass(frozen=True)
class ScoreBreakdown:
    total: float
    components: dict[str, float]
    stale: bool
    evaluated_at: datetime


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def score(inputs: ScoreInputs, weights: ScoreWeights = ScoreWeights()) -> ScoreBreakdown:
    if inputs.stale:
        return ScoreBreakdown(
            total=0.0, components={"staleness_penalty": -100.0},
            stale=True, evaluated_at=inputs.evaluated_at,
        )

    components = {
        "trend_alignment": weights.trend_alignment_max * _clamp01(inputs.trend_alignment_frac),
        "momentum": weights.momentum_max * _clamp01(inputs.momentum_frac),
        "relative_volume": weights.relative_volume_max * _clamp01(inputs.relative_volume_frac),
        "entry_quality": weights.entry_quality_max * _clamp01(inputs.entry_quality_frac),
        "historical_edge": weights.historical_edge_max * _clamp01(inputs.historical_edge_frac),
        "liquidity": weights.liquidity_max * _clamp01(inputs.liquidity_frac),
        "volatility_regime": (
            weights.volatility_regime_max * _clamp01(inputs.volatility_regime_frac)
        ),
        "confirmations": weights.confirmations_max * _clamp01(inputs.confirmations_frac),
        "spread_penalty": -weights.spread_penalty_max * _clamp01(inputs.spread_penalty_frac),
        "slippage_penalty": (
            -weights.slippage_penalty_max * _clamp01(inputs.slippage_penalty_frac)
        ),
    }
    total = max(0.0, min(100.0, sum(components.values())))
    return ScoreBreakdown(
        total=total, components=components, stale=False, evaluated_at=inputs.evaluated_at
    )
