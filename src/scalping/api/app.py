"""FastAPI app factory. CORS locked to the configured dashboard origin
(SCANNER_DASHBOARD_PLAN.md §M: "CORS locked to dashboard origin")."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import async_sessionmaker

from scalping.api.broadcast import Broadcaster
from scalping.api.deps import AppState, CandleLoader
from scalping.api.routers import (
    analytics,
    calibration,
    control,
    developing,
    health,
    lab,
    positions,
    read,
    scanner,
)
from scalping.config.frozen import FrozenParams
from scalping.config.settings import Settings
from scalping.lab.backtest_jobs import BacktestJobRunner
from scalping.market_data.registry import SymbolStateRegistry
from scalping.monitoring.active_trades import ActiveTradeService
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
    active_trades_service: ActiveTradeService | None = None,
    backtest_runner: BacktestJobRunner | None = None,
    candle_loader: CandleLoader | None = None,
) -> FastAPI:
    runner = backtest_runner or BacktestJobRunner()
    runner.set_environment(settings.environment)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await runner.start()
        try:
            yield
        finally:
            await runner.stop()

    app = FastAPI(title="scalping dashboard API", lifespan=lifespan)
    app.state.scalping = AppState(
        sessionmaker=async_sessionmaker(engine), settings=settings, kill_switch=kill_switch,
        scanner=scanner_service or ScannerService(),
        registry=registry or SymbolStateRegistry(FrozenParams()),
        broadcaster=broadcaster or Broadcaster(),
        developing=developing_service or DevelopingSetupsService(),
        active_trades=active_trades_service or ActiveTradeService(),
        backtest_runner=runner,
        candle_loader=candle_loader,
    )

    # Accept configured CORS origins. Comma-separated list supported.
    # Also mirror localhost ↔ 127.0.0.1 for each entry that uses either host.
    origins: set[str] = set()
    for part in settings.dashboard_cors_origin.split(","):
        o = part.strip()
        if not o:
            continue
        origins.add(o)
        if "localhost" in o:
            origins.add(o.replace("localhost", "127.0.0.1"))
        if "127.0.0.1" in o:
            origins.add(o.replace("127.0.0.1", "localhost"))

    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(read.router)
    app.include_router(health.router)
    app.include_router(control.router)
    app.include_router(scanner.router)
    app.include_router(developing.router)
    app.include_router(positions.router)
    app.include_router(analytics.router)
    app.include_router(calibration.router)
    app.include_router(lab.router)
    return app
