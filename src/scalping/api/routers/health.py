"""`/health` — PLAN_OF_ACTION.md §6a: heartbeat age, latency p50/p99, last
self-check result, protection-gap p50/p99."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from scalping.api.deps import AppState, get_session, get_state
from scalping.market_data.staleness import Feed
from scalping.monitoring.stats import percentile
from scalping.persistence.protection_repo import load_recent_protection_ms
from scalping.persistence.selfcheck_repo import load_latest_self_check

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
async def health(
    session: AsyncSession = Depends(get_session),
    state: AppState = Depends(get_state),
):
    self_check = await load_latest_self_check(session)
    protection_samples = await load_recent_protection_ms(session)

    # Feed health answers "why is the scanner empty / why are prices blank"
    # without reading logs: no fresh books means the WS feed is not arriving,
    # which is a proxy/connectivity problem, not a strategy one.
    now = datetime.now(UTC)
    registry = state.registry
    symbols = registry.symbols()
    fresh = 0
    ages: list[float] = []
    for symbol in symbols:
        age = registry.staleness.data_age_ms(symbol, Feed.BOOK_TICKER, now)
        if age is None:
            continue
        ages.append(age)
        if not registry.staleness.is_stale(symbol, Feed.BOOK_TICKER, now):
            fresh += 1

    return {
        "market_data": {
            "symbols_tracked": len(symbols),
            "symbols_with_book": len(ages),
            "symbols_fresh": fresh,
            "book_age_ms_p50": percentile(ages, 50),
            "book_age_ms_p99": percentile(ages, 99),
            "feed_ok": fresh > 0,
        },
        "self_check": (
            {
                "checked_at": self_check.checked_at.isoformat(),
                "environment": self_check.environment,
                "passed": self_check.passed,
                "details": self_check.details,
            }
            if self_check is not None
            else None
        ),
        "protection_gap_ms": {
            "p50": percentile(protection_samples, 50),
            "p99": percentile(protection_samples, 99),
            "n": len(protection_samples),
        },
    }
