"""Probability calibration — SCANNER_DASHBOARD_PLAN.md §S10.

Wilson score interval + min-sample gating. Probabilities may only be exposed
when `n >= min_samples`; otherwise the API returns an explicit insufficient-
sample marker. This is what unblocks percentages in the UI after S8 forbade them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime


def wilson_ci(
    wins: int, n: int, *, z: float = 1.96
) -> tuple[float, float] | None:
    """Wilson score interval for a binomial proportion. Returns None if n=0."""
    if n <= 0:
        return None
    if wins < 0 or wins > n:
        raise ValueError(f"wins={wins} outside [0, {n}]")
    phat = wins / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = phat + z2 / (2 * n)
    margin = z * math.sqrt((phat * (1 - phat) + z2 / (4 * n)) / n)
    lo = max(0.0, (centre - margin) / denom)
    hi = min(1.0, (centre + margin) / denom)
    return lo, hi


@dataclass(frozen=True)
class CalibrationKey:
    strategy_version: str
    side: str
    regime: str
    score_bucket: str  # e.g. "70-80"


@dataclass(frozen=True)
class CalibrationStats:
    key: CalibrationKey
    n: int
    wins: int
    sum_r: float
    updated_at: datetime

    @property
    def win_rate(self) -> float | None:
        return self.wins / self.n if self.n > 0 else None

    @property
    def avg_r(self) -> float | None:
        return self.sum_r / self.n if self.n > 0 else None

    @property
    def profit_factor_proxy(self) -> float | None:
        """Not a true PF (needs gross win/loss split); kept None here — use
        ExpectancyBucket when full PF is required."""
        return None


@dataclass(frozen=True)
class ProbabilityEstimate:
    """Shown only when sample gate passes. `insufficient_sample` otherwise."""

    available: bool
    n: int
    min_samples: int
    win_probability: float | None
    ci_low: float | None
    ci_high: float | None
    expectancy_r: float | None
    reason: str | None = None


def score_bucket(score: float, *, width: float = 10.0) -> str:
    lo = int(score // width) * int(width)
    hi = lo + int(width)
    return f"{lo}-{hi}"


def gate_probability(
    stats: CalibrationStats, *, min_samples: int = 30
) -> ProbabilityEstimate:
    if stats.n < min_samples:
        return ProbabilityEstimate(
            available=False,
            n=stats.n,
            min_samples=min_samples,
            win_probability=None,
            ci_low=None,
            ci_high=None,
            expectancy_r=None,
            reason="insufficient_sample",
        )
    ci = wilson_ci(stats.wins, stats.n)
    assert ci is not None
    return ProbabilityEstimate(
        available=True,
        n=stats.n,
        min_samples=min_samples,
        win_probability=stats.wins / stats.n,
        ci_low=ci[0],
        ci_high=ci[1],
        expectancy_r=stats.sum_r / stats.n,
        reason=None,
    )


def accumulate_calibration(
    existing: CalibrationStats | None,
    *,
    key: CalibrationKey,
    r_multiple: float,
    won: bool,
    updated_at: datetime,
) -> CalibrationStats:
    if existing is None:
        return CalibrationStats(
            key=key,
            n=1,
            wins=1 if won else 0,
            sum_r=r_multiple,
            updated_at=updated_at,
        )
    return CalibrationStats(
        key=key,
        n=existing.n + 1,
        wins=existing.wins + (1 if won else 0),
        sum_r=existing.sum_r + r_multiple,
        updated_at=updated_at,
    )
