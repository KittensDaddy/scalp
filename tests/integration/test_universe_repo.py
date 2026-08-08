from __future__ import annotations

from datetime import UTC, datetime

from scalping.market_data.universe import UniverseEntry
from scalping.persistence.engine import init_db, make_engine
from scalping.persistence.universe_repo import load_eligible_symbols, load_universe, upsert_universe

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


async def test_upsert_and_load_eligible_symbols():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    from sqlalchemy.ext.asyncio import async_sessionmaker

    sm = async_sessionmaker(engine)
    entries = [
        UniverseEntry("BTCUSDT", True, {"base_eligibility": True}, []),
        UniverseEntry("LOWLIQUSDT", False, {"base_eligibility": True}, ["LOW_VOLUME"]),
    ]
    async with sm() as session:
        await upsert_universe(session, entries, now=NOW)
        await session.commit()

    async with sm() as session:
        eligible = await load_eligible_symbols(session)
    assert eligible == ["BTCUSDT"]

    await engine.dispose()


async def test_upsert_updates_existing_row_on_refresh():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    from sqlalchemy.ext.asyncio import async_sessionmaker

    sm = async_sessionmaker(engine)
    async with sm() as session:
        await upsert_universe(
            session, [UniverseEntry("BTCUSDT", True, {}, [])], now=NOW
        )
        await session.commit()

    later = datetime(2026, 8, 9, 13, 0, tzinfo=UTC)
    async with sm() as session:
        await upsert_universe(
            session, [UniverseEntry("BTCUSDT", False, {}, ["LOW_VOLUME"])], now=later
        )
        await session.commit()

    async with sm() as session:
        rows = await load_universe(session)
    assert len(rows) == 1
    assert rows[0].eligible is False
    assert rows[0].updated_at.replace(tzinfo=UTC) == later

    await engine.dispose()


async def test_delisted_symbol_marked_ineligible_on_refresh():
    """A symbol dropped from the exchangeInfo response never gets a new
    UniverseEntry, but a previous refresh's upsert with eligible=False models the
    delist case (the orchestrator is responsible for emitting that entry when a
    symbol disappears — this test locks the repo behavior it depends on)."""
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    from sqlalchemy.ext.asyncio import async_sessionmaker

    sm = async_sessionmaker(engine)
    async with sm() as session:
        await upsert_universe(
            session, [UniverseEntry("DELISTEDUSDT", True, {}, [])], now=NOW
        )
        await session.commit()

    later = datetime(2026, 8, 9, 13, 0, tzinfo=UTC)
    async with sm() as session:
        await upsert_universe(
            session, [UniverseEntry("DELISTEDUSDT", False, {}, ["NOT_ELIGIBLE_CONTRACT"])], now=later
        )
        await session.commit()

    async with sm() as session:
        eligible = await load_eligible_symbols(session)
    assert eligible == []

    await engine.dispose()
