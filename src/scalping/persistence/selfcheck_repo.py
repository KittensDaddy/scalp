"""Persistence for startup self-check results (PLAN_OF_ACTION.md §2a)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scalping.exchanges.binance.selfcheck import SelfCheckResult
from scalping.persistence.models import SelfCheckRow


async def save_self_check(session: AsyncSession, result: SelfCheckResult) -> None:
    session.add(
        SelfCheckRow(
            checked_at=result.checked_at,
            environment=result.environment,
            passed=result.passed,
            details=result.as_details(),
        )
    )


async def load_latest_self_check(session: AsyncSession) -> SelfCheckRow | None:
    """Backs `/health`'s "last self-check result" (PLAN §6a)."""
    stmt = select(SelfCheckRow).order_by(SelfCheckRow.id.desc()).limit(1)
    return (await session.execute(stmt)).scalar_one_or_none()
