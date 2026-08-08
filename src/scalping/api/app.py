"""FastAPI app factory. CORS locked to the configured dashboard origin
(SCANNER_DASHBOARD_PLAN.md §M: "CORS locked to dashboard origin")."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import async_sessionmaker

from scalping.api.broadcast import Broadcaster
from scalping.api.deps import AppState
from scalping.api.routers import control, developing, health, read, scanner
from scalping.config.frozen import FrozenParams
from scalping.config.settings import Settings
from scalping.market_data.registry import SymbolStateRegistry
from scalping.risk.kill_switch import KillSwitch
from scalping.scanner.developing import DevelopingSetupsService
from scalping.scanner.service import ScannerService


def create_app(
    *,
    engine,
    settings: Settings,
    kill_switch: KillSwitch,
    scanner_service: ScannerService | None = None,
    registry: SymbolStateRegistry | None = None,
    broadcaster: Broadcaster | None = None,
    developing_service: DevelopingSetupsService | None = None,
) -> FastAPI:
    app = FastAPI(title="scalping dashboard API")
    app.state.scalping = AppState(
        sessionmaker=async_sessionmaker(engine), settings=settings, kill_switch=kill_switch,
        scanner=scanner_service or ScannerService(),
        registry=registry or SymbolStateRegistry(FrozenParams()),
        broadcaster=broadcaster or Broadcaster(),
        developing=developing_service or DevelopingSetupsService(),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.dashboard_cors_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(read.router)
    app.include_router(health.router)
    app.include_router(control.router)
    app.include_router(scanner.router)
    app.include_router(developing.router)
    return app
