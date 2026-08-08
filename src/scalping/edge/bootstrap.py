"""Percentile bootstrap for a mean — used by the evidence bar (PLAN_OF_ACTION.md
§8, criterion 2: "Net expectancy > 0 with 95% CI excluding zero (bootstrap over
trades)"). Pure-Python; no numpy dependency for one CI calculation.
"""

from __future__ import annotations

import random


def bootstrap_mean_ci(
    values: list[float],
    *,
    n_resamples: int = 2000,
    confidence: float = 0.95,
    rng: random.Random | None = None,
) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    rng = rng or random.Random()
    n = len(values)
    means = []
    for _ in range(n_resamples):
        total = 0.0
        for _ in range(n):
            total += values[rng.randrange(n)]
        means.append(total / n)
    means.sort()
    alpha = (1 - confidence) / 2
    lo_idx = max(0, int(alpha * n_resamples))
    hi_idx = min(n_resamples - 1, int((1 - alpha) * n_resamples) - 1)
    return means[lo_idx], means[hi_idx]
