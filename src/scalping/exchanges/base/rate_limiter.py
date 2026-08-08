"""Token-bucket rate limiter with independent budgets per traffic class.

PLAN_OF_ACTION.md §2a: "Algo endpoint has its own rate limits and failure modes
distinct from /fapi/v1/order — tracked separately in the rate limiter." This module
generalizes that to four independent buckets so backfill traffic can never starve
order placement, and algo-order traffic can never starve plain order traffic.
"""

from __future__ import annotations

import asyncio
import time
from enum import StrEnum

from scalping.exchanges.base.errors import RateLimited


class Budget(StrEnum):
    ORDER = "order"
    ALGO_ORDER = "algo_order"
    MARKET = "market"
    BACKFILL = "backfill"


class TokenBucket:
    """Classic token bucket: `capacity` tokens, refilled at `refill_per_s`."""

    def __init__(self, capacity: float, refill_per_s: float) -> None:
        self.capacity = capacity
        self.refill_per_s = refill_per_s
        self._tokens = capacity
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_per_s)
        self._last_refill = now

    async def acquire(self, weight: float = 1.0, *, block: bool = True) -> None:
        async with self._lock:
            self._refill()
            if self._tokens >= weight:
                self._tokens -= weight
                return
            if not block:
                raise RateLimited(f"insufficient tokens: have {self._tokens:.2f}, need {weight}")
            deficit = weight - self._tokens
            wait_s = deficit / self.refill_per_s
        await asyncio.sleep(wait_s)
        async with self._lock:
            self._refill()
            self._tokens = max(0.0, self._tokens - weight)

    @property
    def available(self) -> float:
        self._refill()
        return self._tokens


class RateLimiter:
    """Owns one :class:`TokenBucket` per :class:`Budget`."""

    def __init__(self, budgets: dict[Budget, TokenBucket] | None = None) -> None:
        self._buckets: dict[Budget, TokenBucket] = budgets or {
            # Futures REST weight budget is ~2400/min per PLAN §2; order-count limits
            # are separate and tighter. Defaults here are conservative starting points,
            # tunable via config without code changes.
            Budget.ORDER: TokenBucket(capacity=300, refill_per_s=300 / 60),
            Budget.ALGO_ORDER: TokenBucket(capacity=300, refill_per_s=300 / 60),
            Budget.MARKET: TokenBucket(capacity=2400, refill_per_s=2400 / 60),
            Budget.BACKFILL: TokenBucket(capacity=1200, refill_per_s=1200 / 60),
        }

    async def acquire(self, budget: Budget, weight: float = 1.0, *, block: bool = True) -> None:
        await self._buckets[budget].acquire(weight, block=block)

    def available(self, budget: Budget) -> float:
        return self._buckets[budget].available
