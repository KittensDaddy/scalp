"""Persistence for cooldowns (SCANNER_DASHBOARD_PLAN.md §H)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scalping.persistence.models import CooldownRow
from scalping.scanner.cooldowns import Cooldown


async def save_cooldown(session: AsyncSession, cooldown: Cooldown) -> None:
    session.add(
        CooldownRow(
            scope=cooldown.scope, key=cooldown.key,
            reason=cooldown.reason, until_ts=cooldown.until,
        )
    )


async def load_active_cooldowns(session: AsyncSession, *, now: datetime) -> list[Cooldown]:
    stmt = select(CooldownRow).where(CooldownRow.until_ts > now)
    rows = (await session.execute(stmt)).scalars().all()
    return [Cooldown(r.scope, r.key, r.reason, r.until_ts) for r in rows]
