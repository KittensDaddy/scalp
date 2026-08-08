from __future__ import annotations

import asyncio

import pytest

from scalping.exchanges.base.errors import RateLimited
from scalping.exchanges.base.rate_limiter import Budget, RateLimiter, TokenBucket


async def test_token_bucket_allows_up_to_capacity():
    bucket = TokenBucket(capacity=5, refill_per_s=1)
    for _ in range(5):
        await bucket.acquire(1, block=False)
    with pytest.raises(RateLimited):
        await bucket.acquire(1, block=False)


async def test_token_bucket_refills_over_time():
    bucket = TokenBucket(capacity=2, refill_per_s=1000)  # fast refill for test speed
    await bucket.acquire(2, block=False)
    await asyncio.sleep(0.01)
    # should have refilled ~10 tokens worth in 10ms at 1000/s, capped at capacity
    await bucket.acquire(1, block=False)


async def test_budgets_are_independent():
    limiter = RateLimiter(
        {
            Budget.ORDER: TokenBucket(capacity=1, refill_per_s=0.001),
            Budget.ALGO_ORDER: TokenBucket(capacity=1, refill_per_s=0.001),
            Budget.MARKET: TokenBucket(capacity=1, refill_per_s=0.001),
            Budget.BACKFILL: TokenBucket(capacity=1, refill_per_s=0.001),
        }
    )
    await limiter.acquire(Budget.ORDER, block=False)
    with pytest.raises(RateLimited):
        await limiter.acquire(Budget.ORDER, block=False)
    # ALGO_ORDER budget is untouched by ORDER exhaustion
    await limiter.acquire(Budget.ALGO_ORDER, block=False)
    await limiter.acquire(Budget.MARKET, block=False)
    await limiter.acquire(Budget.BACKFILL, block=False)


async def test_backfill_exhaustion_does_not_starve_orders():
    limiter = RateLimiter(
        {
            Budget.ORDER: TokenBucket(capacity=1, refill_per_s=0.001),
            Budget.ALGO_ORDER: TokenBucket(capacity=1, refill_per_s=0.001),
            Budget.MARKET: TokenBucket(capacity=1, refill_per_s=0.001),
            Budget.BACKFILL: TokenBucket(capacity=1, refill_per_s=0.001),
        }
    )
    await limiter.acquire(Budget.BACKFILL, block=False)
    with pytest.raises(RateLimited):
        await limiter.acquire(Budget.BACKFILL, block=False)
    await limiter.acquire(Budget.ORDER, block=False)  # unaffected
