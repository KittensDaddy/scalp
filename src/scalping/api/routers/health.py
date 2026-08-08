"""`/health` — PLAN_OF_ACTION.md §6a: heartbeat age, latency p50/p99, last
self-check result, protection-gap p50/p99."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from scalping.api.deps import get_session
from scalping.monitoring.stats import percentile
from scalping.persistence.protection_repo import load_recent_protection_ms
from scalping.persistence.selfcheck_repo import load_latest_self_check

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
async def health(session: AsyncSession = Depends(get_session)):
    self_check = await load_latest_self_check(session)
    protection_samples = await load_recent_protection_ms(session)

    return {
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
