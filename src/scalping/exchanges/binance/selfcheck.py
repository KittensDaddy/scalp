"""Startup self-check — PLAN_OF_ACTION.md §2a.

"Submit and cancel a minimal algo order, open one WS connection per category
(/public, /market, /private), verify expected message shapes. Any divergence from
the [exchange facts] table above -> refuse to start trading, raise incident."
"Self-check results persisted with timestamps."

Orchestration here takes the algo-order round-trip and one sample message per
category as injectable callables/values, so the check logic is testable without a
real exchange connection; `cli`/the trading loop wire real REST/WS calls at startup.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from scalping.exchanges.base.errors import SelfCheckFailed
from scalping.exchanges.binance.shapes import (
    ShapeMismatch,
    check_algo_order_ack_shape,
    check_book_ticker_shape,
    check_kline_shape,
    check_user_stream_shape,
)
from scalping.exchanges.binance.ws import StreamCategory


@dataclass(frozen=True)
class SelfCheckStepResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class SelfCheckResult:
    checked_at: datetime
    environment: str
    passed: bool
    steps: list[SelfCheckStepResult] = field(default_factory=list)

    def as_details(self) -> dict[str, Any]:
        return {
            "steps": [
                {"name": s.name, "passed": s.passed, "detail": s.detail} for s in self.steps
            ]
        }


_CATEGORY_CHECKERS: dict[StreamCategory, Callable[[dict], None]] = {
    StreamCategory.PUBLIC: check_book_ticker_shape,
    StreamCategory.MARKET: check_kline_shape,
    StreamCategory.PRIVATE: check_user_stream_shape,
}


async def run_self_check(
    *,
    environment: str,
    place_and_cancel_algo_order: Callable[[], Awaitable[dict[str, Any]]],
    sample_messages: dict[StreamCategory, dict[str, Any]],
    now: datetime,
) -> SelfCheckResult:
    steps: list[SelfCheckStepResult] = []

    try:
        ack = await place_and_cancel_algo_order()
        check_algo_order_ack_shape(ack)
        steps.append(SelfCheckStepResult("algo_order_submit_cancel", True))
    except Exception as e:
        steps.append(SelfCheckStepResult("algo_order_submit_cancel", False, str(e)))

    for category, checker in _CATEGORY_CHECKERS.items():
        step_name = f"ws_shape_{category.value}"
        msg = sample_messages.get(category)
        try:
            if msg is None:
                raise ShapeMismatch(f"no sample message received for category {category.value}")
            checker(msg)
            steps.append(SelfCheckStepResult(step_name, True))
        except Exception as e:
            steps.append(SelfCheckStepResult(step_name, False, str(e)))

    passed = all(s.passed for s in steps)
    return SelfCheckResult(checked_at=now, environment=environment, passed=passed, steps=steps)


def require_passed(result: SelfCheckResult) -> None:
    """Trading must refuse to start if this raises."""
    if not result.passed:
        failed = [s.name for s in result.steps if not s.passed]
        raise SelfCheckFailed(
            f"startup self-check failed ({result.environment}): {', '.join(failed)}"
        )
