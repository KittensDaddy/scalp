from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from scalping.persistence.engine import PersistenceWriter, init_db, make_engine
from scalping.persistence.models import KillSwitchRow, SignalRow


@pytest.fixture
async def engine():
    eng = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(eng)
    yield eng
    await eng.dispose()


async def test_init_db_creates_all_tables(engine):
    async with engine.connect() as conn:
        result = await conn.run_sync(
            lambda sync_conn: sync_conn.dialect.get_table_names(sync_conn)
        )
    for table in ("signals", "rejections", "trades", "entry_attempts", "self_checks", "kill_switch"):
        assert table in result


async def test_persistence_writer_enqueues_and_flushes(engine):
    writer = PersistenceWriter(engine)
    writer.start()

    async def job(session):
        session.add(
            SignalRow(
                symbol="BTCUSDT",
                side="LONG",
                strategy_version="caems_v2",
                signal_time=datetime.now(UTC),
                entry_reference=100.0,
                stop=99.5,
                take_profit=100.7,
                strength=0.4,
                config_hash="abc123",
            )
        )

    writer.enqueue(job)
    await writer.flush()
    await writer.stop()

    from sqlalchemy.ext.asyncio import async_sessionmaker

    sm = async_sessionmaker(engine)
    async with sm() as session:
        rows = (await session.execute(select(SignalRow))).scalars().all()
    assert len(rows) == 1
    assert rows[0].symbol == "BTCUSDT"
    assert rows[0].config_hash == "abc123"


async def test_kill_switch_row_persists_and_reads_back(engine):
    writer = PersistenceWriter(engine)
    writer.start()

    async def job(session):
        session.add(KillSwitchRow(killed=True, reason="manual", set_at=datetime.now(UTC)))

    writer.enqueue(job)
    await writer.flush()
    await writer.stop()

    from sqlalchemy.ext.asyncio import async_sessionmaker

    sm = async_sessionmaker(engine)
    async with sm() as session:
        row = (await session.execute(select(KillSwitchRow))).scalar_one()
    assert row.killed is True
