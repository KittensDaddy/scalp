"""Persistence for developing setups (SCANNER_DASHBOARD_PLAN.md §H)."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from scalping.persistence.models import DevelopingSetupRow
from scalping.scanner.developing import DevelopingSetup


async def save_developing_setup(
    session: AsyncSession, setup: DevelopingSetup, *, strategy_version: str
) -> None:
    session.add(
        DevelopingSetupRow(
            symbol=setup.symbol, side=setup.side.value, strategy_version=strategy_version,
            ts=setup.detected_at, score=setup.score,
            missing_conditions=setup.missing_conditions, projections=setup.projections,
        )
    )


async def replace_developing_setups(
    session: AsyncSession, setups: list[DevelopingSetup], *, strategy_version: str
) -> None:
    """Full-refresh write: clears prior rows for this strategy and inserts the
    current pass's setups, mirroring how the scanner treats each evaluation pass
    as the new source of truth rather than an append-only log."""
    await session.execute(
        delete(DevelopingSetupRow).where(DevelopingSetupRow.strategy_version == strategy_version)
    )
    for setup in setups:
        await save_developing_setup(session, setup, strategy_version=strategy_version)


async def load_developing_setups(
    session: AsyncSession, *, strategy_version: str
) -> list[DevelopingSetupRow]:
    """`replace_developing_setups` keeps only the latest pass's rows per strategy, so
    this is simply every row for that strategy, ranked by score."""
    stmt = (
        select(DevelopingSetupRow)
        .where(DevelopingSetupRow.strategy_version == strategy_version)
        .order_by(DevelopingSetupRow.score.desc())
    )
    return list((await session.execute(stmt)).scalars().all())
