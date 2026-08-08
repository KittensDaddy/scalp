"""Shared FastAPI dependencies — one `AppState` object holds everything the routers
need, attached to `app.state` so tests can construct it explicitly (in-memory DB,
throwaway kill switch) without touching global state.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from scalping.api.broadcast import Broadcaster
from scalping.config.settings import Settings
from scalping.market_data.registry import SymbolStateRegistry
from scalping.risk.kill_switch import KillSwitch
from scalping.scanner.developing import DevelopingSetupsService
from scalping.scanner.service import ScannerService


@dataclass
class AppState:
    sessionmaker: async_sessionmaker
    settings: Settings
    kill_switch: KillSwitch
    scanner: ScannerService
    registry: SymbolStateRegistry
    broadcaster: Broadcaster
    developing: DevelopingSetupsService


def get_state(request: Request) -> AppState:
    return request.app.state.scalping


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    state: AppState = get_state(request)
    async with state.sessionmaker() as session:
        yield session
