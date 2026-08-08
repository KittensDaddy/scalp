from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import async_sessionmaker

from scalping.exchanges.binance.selfcheck import SelfCheckResult, SelfCheckStepResult
from scalping.persistence.engine import init_db, make_engine
from scalping.persistence.selfcheck_repo import load_latest_self_check, save_self_check

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


async def test_save_and_load_latest_self_check():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    sessionmaker = async_sessionmaker(engine)

    result = SelfCheckResult(
        checked_at=NOW, environment="testnet", passed=True,
        steps=[SelfCheckStepResult("algo_order_submit_cancel", True)],
    )
    async with sessionmaker() as session:
        await save_self_check(session, result)
        await session.commit()

    async with sessionmaker() as session:
        row = await load_latest_self_check(session)
    assert row is not None
    assert row.passed is True
    assert row.environment == "testnet"
    assert row.details["steps"][0]["name"] == "algo_order_submit_cancel"

    await engine.dispose()


async def test_load_latest_returns_most_recent():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    sessionmaker = async_sessionmaker(engine)

    older = SelfCheckResult(checked_at=NOW, environment="testnet", passed=False, steps=[])
    newer = SelfCheckResult(checked_at=NOW, environment="testnet", passed=True, steps=[])

    async with sessionmaker() as session:
        await save_self_check(session, older)
        await save_self_check(session, newer)
        await session.commit()

    async with sessionmaker() as session:
        row = await load_latest_self_check(session)
    assert row is not None
    assert row.passed is True

    await engine.dispose()
