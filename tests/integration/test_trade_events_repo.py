"""Trade-events persistence — S8 lifecycle timeline storage."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from scalping.domain.models import TradeEvent, TradeEventType
from scalping.persistence.engine import init_db, make_engine
from scalping.persistence.trade_events_repo import load_trade_events, save_trade_event

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


@pytest.fixture
async def sessionmaker():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    sm = async_sessionmaker(engine)
    yield sm
    await engine.dispose()


async def test_save_and_load_trade_events_in_order(sessionmaker):
    events = [
        TradeEvent(
            trade_id="t1", symbol="BTCUSDT", event_type=TradeEventType.OPENED,
            ts=NOW, payload={"entry_price": 100.0},
        ),
        TradeEvent(
            trade_id="t1", symbol="BTCUSDT", event_type=TradeEventType.PROTECTED,
            ts=NOW, payload={"t_protection_ms": 90.0},
        ),
        TradeEvent(
            trade_id="t1", symbol="BTCUSDT", event_type=TradeEventType.CLOSED,
            ts=NOW, payload={"exit_reason": "TAKE_PROFIT", "r_multiple": 1.35},
        ),
    ]
    async with sessionmaker() as session:
        for e in events:
            await save_trade_event(session, e)
        await session.commit()
        rows = await load_trade_events(session, "t1")

    assert [r.event_type for r in rows] == ["OPENED", "PROTECTED", "CLOSED"]
    assert rows[1].payload["t_protection_ms"] == 90.0


async def test_save_rejects_probability_payload(sessionmaker):
    bad = TradeEvent(
        trade_id="t1", symbol="BTCUSDT", event_type=TradeEventType.SCORE_CHANGED,
        ts=NOW, payload={"win_probability": 0.7},
    )
    async with sessionmaker() as session:
        with pytest.raises(ValueError, match="probability"):
            await save_trade_event(session, bad)
