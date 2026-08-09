"""Paper executor entry path."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scalping.config.settings import EffectiveConfig
from scalping.domain.models import BookTicker, Side, SignalCandidate
from scalping.monitoring.active_trades import ActiveTradeService
from scalping.paper.venue import PaperVenue
from scalping.runtime.paper_executor import PaperExecutor

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_paper_executor_opens_and_protects():
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
        venue=venue, active_trades=active, config=EffectiveConfig(), entry_ttl_s=0.01
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
        config_hash="abc",
    )
    await ex.on_signals([signal], NOW)
    # allow create_task to finish
    import asyncio

    await asyncio.sleep(0.1)
    snap = active.snapshot()
    assert len(snap.positions) == 1
    assert snap.positions[0].protected is True
