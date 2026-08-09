"""Closed-trade + calibration persistence."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from scalping.domain.models import Position, Side
from scalping.monitoring.active_trades import ActiveTradeService
from scalping.persistence.engine import init_db, make_engine
from scalping.persistence.models import CalibrationStatsRow, EntryAttemptRow, TradeRow
from scalping.persistence.trades_repo import (
    record_calibration_sample,
    save_closed_trade,
    save_entry_attempt,
)

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


@pytest.fixture
async def sessionmaker():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    sm = async_sessionmaker(engine)
    yield sm
    await engine.dispose()


async def test_save_closed_trade_and_calibration(sessionmaker):
    active = ActiveTradeService()
    pos = Position(
        symbol="BTCUSDT",
        side=Side.LONG,
        entry_price=100.0,
        quantity=0.1,
        stop_price=99.0,
        take_profit_price=101.35,
        opened_at=NOW,
        protected=True,
    )
    active.open_trade(trade_id="t1", position=pos, score=75.0, ts=NOW)
    active.update_price("t1", 101.35)
    closed, _, _ = active.close_trade(
        "t1", exit_price=101.35, exit_reason="TAKE_PROFIT", ts=NOW
    )

    async with sessionmaker() as session:
        row = await save_closed_trade(
            session, trade=closed, config_hash="abc", regime="trend_up"
        )
        cal = await record_calibration_sample(
            session,
            strategy_version="caems_v2",
            side="LONG",
            regime="trend_up",
            score=75.0,
            r_multiple=closed.unrealized_r,
            updated_at=NOW,
        )
        trade_id = row.trade_id
        assert trade_id == "t1"
        assert row.mae is not None
        assert "auto_notes" in (row.cost_breakdown or {})
        assert cal.n == 1
        assert cal.score_bucket == "70-80"
        await session.commit()

        # idempotent trade save
        again = await save_closed_trade(
            session, trade=closed, config_hash="abc", regime="trend_up"
        )
        again_id = again.trade_id
        await session.commit()
        assert again_id == trade_id

        # accumulate second sample
        await record_calibration_sample(
            session,
            strategy_version="caems_v2",
            side="LONG",
            regime="trend_up",
            score=75.0,
            r_multiple=-1.0,
            updated_at=NOW,
        )
        await session.commit()
        cal2 = (
            await session.execute(select(CalibrationStatsRow))
        ).scalar_one()
        assert cal2.n == 2
        assert cal2.wins == 1


async def test_save_entry_attempt(sessionmaker):
    async with sessionmaker() as session:
        await save_entry_attempt(
            session,
            symbol="ETHUSDT",
            side="LONG",
            outcome="ABANDONED",
            attempted_at=NOW,
            config_hash="h",
        )
        await session.commit()
        rows = (await session.execute(select(EntryAttemptRow))).scalars().all()
    assert len(rows) == 1
    assert rows[0].outcome == "ABANDONED"


@pytest.mark.asyncio
async def test_paper_executor_persists_on_close(sessionmaker):
    from scalping.config.settings import EffectiveConfig
    from scalping.domain.models import BookTicker, SignalCandidate
    from scalping.paper.venue import PaperVenue
    from scalping.runtime.paper_executor import PaperExecutor

    venue = PaperVenue()
    venue.on_book_ticker(
        BookTicker(
            symbol="BTCUSDT",
            bid_price=100.0,
            bid_qty=1.0,
            ask_price=100.1,
            ask_qty=1.0,
            event_time=NOW,
        )
    )
    active = ActiveTradeService()
    ex = PaperExecutor(
        venue=venue,
        active_trades=active,
        config=EffectiveConfig(),
        entry_ttl_s=0.01,
        sessionmaker=sessionmaker,
        config_hash="cfg",
    )
    signal = SignalCandidate(
        symbol="BTCUSDT",
        side=Side.LONG,
        strategy_version="caems_v2",
        signal_time=NOW,
        entry_reference=100.0,
        stop=99.0,
        take_profit=101.35,
        strength=0.5,
        config_hash="cfg",
    )
    await ex.on_signals([signal], NOW, scores={"BTCUSDT": 72.0})
    import asyncio

    await asyncio.sleep(0.15)
    assert len(active.snapshot().positions) == 1
    trade_id = active.snapshot().positions[0].trade_id

    # Force venue flat → sync_closes persists
    venue._positions.clear()
    await ex.sync_closes(NOW)

    async with sessionmaker() as session:
        trades = (await session.execute(select(TradeRow))).scalars().all()
        attempts = (await session.execute(select(EntryAttemptRow))).scalars().all()
        cals = (await session.execute(select(CalibrationStatsRow))).scalars().all()
    assert len(trades) == 1
    assert trades[0].trade_id == trade_id
    assert len(attempts) >= 1
    assert len(cals) == 1
