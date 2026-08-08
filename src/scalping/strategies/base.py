"""Strategy plugin protocol.

SCANNER_DASHBOARD_PLAN.md §A: "CAEMS strategy — First Strategy.evaluate() plugin;
wrap, don't modify rules." This protocol is the seam the scanner's StrategyRunner
(phase S4) will call through; CAEMS (P3) is the only implementation for now.
"""

from __future__ import annotations

from typing import Protocol

from scalping.domain.models import StrategyEvaluation


class Strategy(Protocol):
    strategy_version: str

    def evaluate(self, *args: object, **kwargs: object) -> StrategyEvaluation:
        """Implementations define their own typed inputs; this Protocol exists so
        the runner can type-check `strategy_version` and the common return type."""
        ...
