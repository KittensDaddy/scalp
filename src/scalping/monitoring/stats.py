"""Small stats helpers for /health (PLAN_OF_ACTION.md §6a: latency p50/p99,
protection-gap p50/p99)."""

from __future__ import annotations

import math


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile, `p` in [0, 100]. Returns None for an empty input."""
    if not values:
        return None
    s = sorted(values)
    idx = max(0, min(len(s) - 1, math.ceil(p / 100 * len(s)) - 1))
    return s[idx]
