"""Latency tracking — SCANNER_DASHBOARD_PLAN.md §D: "event E (exchange ts) ->
local receipt -> state update -> strategy eval -> publish; histogram per stage
exposed at /api/v1/system."""

from __future__ import annotations

from collections import deque
from datetime import datetime

from scalping.monitoring.stats import percentile


class LatencyTracker:
    def __init__(self, *, window: int = 2000) -> None:
        self._samples_ms: dict[str, deque[float]] = {}
        self._window = window

    def record(self, stage: str, *, exchange_ts: datetime, local_ts: datetime) -> None:
        delta_ms = (local_ts - exchange_ts).total_seconds() * 1000.0
        if stage not in self._samples_ms:
            self._samples_ms[stage] = deque(maxlen=self._window)
        self._samples_ms[stage].append(delta_ms)

    def stats(self, stage: str) -> dict[str, float | int | None]:
        samples = list(self._samples_ms.get(stage, []))
        return {"p50": percentile(samples, 50), "p99": percentile(samples, 99), "n": len(samples)}

    def stages(self) -> list[str]:
        return list(self._samples_ms)
