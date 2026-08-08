"""Correlation/exposure grouping — SCANNER_DASHBOARD_PLAN.md §B: "Correlation/
exposure grouping in risk engine." Distinct from the per-class position cap
already in `risk.engine.RiskEngine` (`max_positions_in_class`): a correlation
group can span multiple symbol classes (e.g. "high BTC-beta" cuts across
major_alt and meme), so it's tracked separately.
"""

from __future__ import annotations


class ExposureLimiter:
    def __init__(self) -> None:
        self._open_by_group: dict[str, int] = {}

    def on_opened(self, group: str) -> None:
        self._open_by_group[group] = self._open_by_group.get(group, 0) + 1

    def on_closed(self, group: str) -> None:
        self._open_by_group[group] = max(0, self._open_by_group.get(group, 0) - 1)

    def open_count(self, group: str) -> int:
        return self._open_by_group.get(group, 0)

    def within_limit(self, group: str, max_positions: int) -> bool:
        return self.open_count(group) < max_positions
