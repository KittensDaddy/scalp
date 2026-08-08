from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker

from scalping.persistence.cooldown_repo import load_active_cooldowns, save_cooldown
from scalping.persistence.engine import init_db, make_engine
from scalping.scanner.cooldowns import Cooldown

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


async def test_save_and_load_active_cooldowns():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    sm = async_sessionmaker(engine)

    async with sm() as session:
        await save_cooldown(session, Cooldown("symbol", "BTCUSDT", "RISK_LIMIT", NOW + timedelta(minutes=5)))
        await save_cooldown(session, Cooldown("symbol", "ETHUSDT", "RISK_LIMIT", NOW - timedelta(minutes=5)))
        await session.commit()

    async with sm() as session:
        active = await load_active_cooldowns(session, now=NOW)
    assert [c.key for c in active] == ["BTCUSDT"]

    await engine.dispose()
