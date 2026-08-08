"""Persistence for protection-gap measurements (PLAN_OF_ACTION.md §5a)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scalping.persistence.models import ProtectionEventRow


async def record_protection_event(
    session: AsyncSession, *, symbol: str, measured_at: datetime,
    t_protection_ms: float, protected: bool,
) -> None:
    session.add(
        ProtectionEventRow(
            symbol=symbol, measured_at=measured_at,
            t_protection_ms=t_protection_ms, protected=protected,
        )
    )


async def load_recent_protection_ms(session: AsyncSession, limit: int = 1000) -> list[float]:
    stmt = (
        select(ProtectionEventRow.t_protection_ms)
        .order_by(ProtectionEventRow.id.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())
