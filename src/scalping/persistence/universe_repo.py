"""Persistence for the symbol universe (SCANNER_DASHBOARD_PLAN.md §H)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_upsert
from sqlalchemy.ext.asyncio import AsyncSession

from scalping.market_data.universe import UniverseEntry
from scalping.persistence.models import SymbolUniverseRow


async def upsert_universe(
    session: AsyncSession, entries: list[UniverseEntry], *, now: datetime
) -> None:
    for entry in entries:
        stmt = sqlite_upsert(SymbolUniverseRow).values(
            symbol=entry.symbol, eligible=entry.eligible,
            filters_passed=entry.filters_passed, reasons=entry.reasons, updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[SymbolUniverseRow.symbol],
            set_={
                "eligible": entry.eligible, "filters_passed": entry.filters_passed,
                "reasons": entry.reasons, "updated_at": now,
            },
        )
        await session.execute(stmt)


async def load_eligible_symbols(session: AsyncSession) -> list[str]:
    stmt = select(SymbolUniverseRow.symbol).where(SymbolUniverseRow.eligible.is_(True))
    return list((await session.execute(stmt)).scalars().all())


async def load_universe(session: AsyncSession) -> list[SymbolUniverseRow]:
    return list((await session.execute(select(SymbolUniverseRow))).scalars().all())
