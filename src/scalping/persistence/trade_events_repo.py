"""Persistence for trade lifecycle events (SCANNER_DASHBOARD_PLAN.md §H / S8)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scalping.domain.models import TradeEvent
from scalping.monitoring.active_trades import reject_probability_fields
from scalping.persistence.models import TradeEventRow


async def save_trade_event(session: AsyncSession, event: TradeEvent) -> None:
    reject_probability_fields(event.payload)
    session.add(
        TradeEventRow(
            trade_id=event.trade_id,
            symbol=event.symbol,
            event_type=event.event_type.value,
            ts=event.ts,
            payload=event.payload,
        )
    )


async def load_trade_events(
    session: AsyncSession, trade_id: str
) -> list[TradeEventRow]:
    stmt = (
        select(TradeEventRow)
        .where(TradeEventRow.trade_id == trade_id)
        .order_by(TradeEventRow.ts.asc(), TradeEventRow.id.asc())
    )
    return list((await session.execute(stmt)).scalars().all())
