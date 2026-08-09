"""Trading-loop supervisor."""

from __future__ import annotations

import asyncio

import pytest

from scalping.api.broadcast import Broadcaster
from scalping.monitoring.active_trades import ActiveTradeService
from scalping.risk.kill_switch import KillSwitch
from scalping.runtime.supervisor import SupervisorConfig, TraderSupervisor
from scalping.scanner.developing import DevelopingSetupsService
from scalping.scanner.service import ScannerService


@pytest.mark.asyncio
async def test_supervisor_ticks_and_heartbeats():
    ticks_seen: list[int] = []

    async def on_tick(sup: TraderSupervisor, now) -> None:
        ticks_seen.append(sup.ticks)

    ks = KillSwitch(control_token="ctrl", unkill_token="unkill")
    bc = Broadcaster()
    q = bc.subscribe("system")
    sup = TraderSupervisor(
        kill_switch=ks,
        scanner=ScannerService(),
        developing=DevelopingSetupsService(),
        active_trades=ActiveTradeService(),
        broadcaster=bc,
        config=SupervisorConfig(eval_interval_s=0.01, heartbeat_interval_s=0.05),
        on_tick=on_tick,
    )
    await sup.start()
    await asyncio.sleep(0.08)
    await sup.stop()
    assert sup.ticks >= 2
    assert len(ticks_seen) >= 2
    msg = await asyncio.wait_for(q.get(), timeout=1.0)
    assert msg["type"] == "heartbeat"


@pytest.mark.asyncio
async def test_supervisor_skips_on_tick_when_killed():
    called = 0

    async def on_tick(sup, now) -> None:
        nonlocal called
        called += 1

    ks = KillSwitch(control_token="ctrl", unkill_token="unkill")
    ks.engage("ctrl", "test")
    sup = TraderSupervisor(
        kill_switch=ks,
        scanner=ScannerService(),
        developing=DevelopingSetupsService(),
        active_trades=ActiveTradeService(),
        broadcaster=Broadcaster(),
        config=SupervisorConfig(eval_interval_s=0.01, heartbeat_interval_s=1.0),
        on_tick=on_tick,
    )
    await sup.start()
    await asyncio.sleep(0.05)
    await sup.stop()
    assert called == 0
