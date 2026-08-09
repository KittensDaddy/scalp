"""Trading-loop supervisor — PLAN_OF_ACTION.md §6b.

Wires market-data → scanner → (optional) entry path pieces into one asyncio
process. Paper/testnet/live differ only by the venue adapter injected here.
This is the missing `scalping --run` process; S1-S8 were DI-tested without it.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from scalping.api.broadcast import Broadcaster
from scalping.monitoring.active_trades import ActiveTradeService
from scalping.risk.kill_switch import KillSwitch
from scalping.scanner.developing import DevelopingSetupsService
from scalping.scanner.service import ScannerService

log = logging.getLogger(__name__)


@dataclass
class SupervisorConfig:
    symbols: list[str] = field(default_factory=lambda: ["BTCUSDT", "ETHUSDT"])
    eval_interval_s: float = 1.0
    heartbeat_interval_s: float = 5.0


@dataclass
class TraderSupervisor:
    """Owns the long-running tasks for one trading process.

    Evaluation callbacks are injectable so unit tests can drive the loop without
    a live Binance connection. In production, `on_tick` runs StrategyRunner +
    publishes into ScannerService / DevelopingSetupsService / ActiveTradeService
    and fans deltas out through the Broadcaster.
    """

    kill_switch: KillSwitch
    scanner: ScannerService
    developing: DevelopingSetupsService
    active_trades: ActiveTradeService
    broadcaster: Broadcaster
    config: SupervisorConfig = field(default_factory=SupervisorConfig)
    on_tick: Any = None  # async (supervisor, now) -> None
    _running: bool = False
    _tasks: list[asyncio.Task] = field(default_factory=list)
    ticks: int = 0
    last_heartbeat_at: datetime | None = None

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._tasks = [
            asyncio.create_task(self._eval_loop(), name="eval_loop"),
            asyncio.create_task(self._heartbeat_loop(), name="heartbeat_loop"),
        ]
        log.info("TraderSupervisor started symbols=%s", self.config.symbols)

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        log.info("TraderSupervisor stopped after %s ticks", self.ticks)

    async def _eval_loop(self) -> None:
        while self._running:
            now = datetime.now(UTC)
            if self.kill_switch.killed:
                await asyncio.sleep(self.config.eval_interval_s)
                continue
            if self.on_tick is not None:
                await self.on_tick(self, now)
            self.ticks += 1
            # publish heartbeat-friendly scanner seq even when on_tick is a no-op
            await self.broadcaster.publish(
                "system",
                {
                    "type": "heartbeat",
                    "ts": now.isoformat(),
                    "ticks": self.ticks,
                    "killed": self.kill_switch.killed,
                },
            )
            await asyncio.sleep(self.config.eval_interval_s)

    async def _heartbeat_loop(self) -> None:
        while self._running:
            self.last_heartbeat_at = datetime.now(UTC)
            await asyncio.sleep(self.config.heartbeat_interval_s)
