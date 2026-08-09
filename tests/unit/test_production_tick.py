"""Production tick + context builder."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from scalping.api.broadcast import Broadcaster
from scalping.config.frozen import FrozenParams
from scalping.config.settings import EffectiveConfig
from scalping.domain.models import BookTicker, Candle
from scalping.market_data.registry import SymbolStateRegistry
from scalping.monitoring.active_trades import ActiveTradeService
from scalping.risk.kill_switch import KillSwitch
from scalping.runtime.context import build_eval_context, indicators_ready
from scalping.runtime.tick import ProductionTick
from scalping.scanner.developing import DevelopingSetupsService
from scalping.scanner.runner import StrategyRunner
from scalping.scanner.service import ScannerService

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def _warm(registry: SymbolStateRegistry, symbol: str = "BTCUSDT", n: int = 300) -> None:
    price = 100.0
    for i in range(n):
        ts = NOW - timedelta(minutes=n - i)
        # gentle uptrend so 1m/5m EMAs can align long
        close = price + i * 0.02
        candle = Candle(
            symbol=symbol,
            timeframe="1m",
            open_time=ts,
            close_time=ts + timedelta(minutes=1),
            open=close - 0.01,
            high=close + 0.05,
            low=close - 0.05,
            close=close,
            quote_volume=2_000_000.0,
        )
        registry.on_kline_1m_closed(candle)
        if (i + 1) % 5 == 0:

            # feed rolling 5m by re-aggregating recent — simpler: emit every 5 bars
            c5 = Candle(
                symbol=symbol,
                timeframe="5m",
                open_time=ts - timedelta(minutes=4),
                close_time=ts + timedelta(minutes=1),
                open=close - 0.1,
                high=close + 0.1,
                low=close - 0.1,
                close=close,
                quote_volume=10_000_000.0,
            )
            registry.on_kline_5m_closed(c5)
    registry.on_book_ticker(
        BookTicker(
            symbol=symbol,
            bid_price=price + n * 0.02 - 0.01,
            bid_qty=1.0,
            ask_price=price + n * 0.02 + 0.01,
            ask_qty=1.0,
            event_time=NOW,
        )
    )


def test_indicators_ready_after_warm():
    registry = SymbolStateRegistry(FrozenParams())
    _warm(registry)
    state = registry.get("BTCUSDT")
    assert state is not None
    assert indicators_ready(state)


def test_build_eval_context_returns_context():
    registry = SymbolStateRegistry(FrozenParams())
    _warm(registry)
    state = registry.get("BTCUSDT")
    assert state is not None
    ctx = build_eval_context(
        state, config=EffectiveConfig(), evaluated_at=NOW, kill_switch=None
    )
    assert ctx is not None
    assert ctx.symbol == "BTCUSDT"


@pytest.mark.asyncio
async def test_production_tick_publishes_scanner():
    registry = SymbolStateRegistry(FrozenParams())
    _warm(registry)
    scanner = ScannerService()
    developing = DevelopingSetupsService()
    bc = Broadcaster()
    q = bc.subscribe("scanner")
    tick = ProductionTick(
        registry=registry,
        runner=StrategyRunner(scanner=scanner, developing=developing),
        scanner=scanner,
        developing=developing,
        active_trades=ActiveTradeService(),
        broadcaster=bc,
        kill_switch=KillSwitch(control_token="c", unkill_token="u"),
        config=EffectiveConfig(),
        symbols=["BTCUSDT"],
        execute=False,
    )
    result = await tick.run(NOW)
    assert result.delta.seq >= 1
    msg = await q.get()
    assert msg["type"] == "snapshot"
    assert len(msg["rows"]) >= 1


@pytest.mark.asyncio
async def test_production_tick_shows_warming_rows_before_indicators_ready():
    registry = SymbolStateRegistry(FrozenParams())
    scanner = ScannerService()
    developing = DevelopingSetupsService()
    tick = ProductionTick(
        registry=registry,
        runner=StrategyRunner(scanner=scanner, developing=developing),
        scanner=scanner,
        developing=developing,
        active_trades=ActiveTradeService(),
        broadcaster=Broadcaster(),
        kill_switch=KillSwitch(control_token="c", unkill_token="u"),
        config=EffectiveConfig(),
        symbols=["ETHUSDT"],
        execute=False,
    )
    await tick.run(NOW)
    rows = scanner.snapshot().rows
    assert len(rows) == 1
    assert rows[0].symbol == "ETHUSDT"
    assert rows[0].strategy == "warming"
    assert rows[0].rejection_reason.value == "DATA_UNAVAILABLE"
