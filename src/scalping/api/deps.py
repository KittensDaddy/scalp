"""Shared FastAPI dependencies — one `AppState` object holds everything the routers
need, attached to `app.state` so tests can construct it explicitly (in-memory DB,
throwaway kill switch) without touching global state.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from scalping.api.broadcast import Broadcaster
from scalping.config.settings import Settings
from scalping.domain.models import Candle
from scalping.lab.backtest_jobs import BacktestJobRunner
from scalping.market_data.registry import SymbolStateRegistry
from scalping.monitoring.active_trades import ActiveTradeService
from scalping.risk.kill_switch import KillSwitch
from scalping.scanner.developing import DevelopingSetupsService
from scalping.scanner.service import ScannerService

CandleLoader = Callable[
    [list[str], datetime, datetime],
    Awaitable[tuple[list[Candle], list[Candle]]],
]


@dataclass
class AppState:
    sessionmaker: async_sessionmaker
    settings: Settings
    kill_switch: KillSwitch
    scanner: ScannerService
    registry: SymbolStateRegistry
    broadcaster: Broadcaster
    developing: DevelopingSetupsService
    active_trades: ActiveTradeService
    backtest_runner: BacktestJobRunner
    candle_loader: CandleLoader | None = None
    extras: dict[str, Any] = field(default_factory=dict)


def get_state(request: Request) -> AppState:
    return request.app.state.scalping


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    state: AppState = get_state(request)
    async with state.sessionmaker() as session:
        yield session
