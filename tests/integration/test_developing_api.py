from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from scalping.api.app import create_app
from scalping.config.settings import Settings
from scalping.domain.models import Side
from scalping.persistence.engine import init_db, make_engine
from scalping.risk.kill_switch import KillSwitch
from scalping.scanner.developing import (
    DevelopingSetupsService,
    NearTriggerConfig,
    detect_developing_setup,
)
from scalping.strategies.caems.diagnostics import ConditionCheck

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def _sample_setup():
    conditions = [ConditionCheck("spread", False, "spread 5.0bps needs <= 2.0bps")]
    return detect_developing_setup(
        symbol="BTCUSDT", side=Side.LONG, score=55.0, accepted=False,
        conditions=conditions, config=NearTriggerConfig(score_threshold=70.0, score_delta=20.0),
        evaluated_at=NOW,
    )


@pytest.fixture
async def app_and_developing():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    settings = Settings(control_token="ctrl", dashboard_unkill_token="unkill")
    kill_switch = KillSwitch(control_token="ctrl", unkill_token="unkill")
    developing = DevelopingSetupsService()
    app = create_app(
        engine=engine, settings=settings, kill_switch=kill_switch, developing_service=developing,
    )
    yield app, developing
    await engine.dispose()


async def _client(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_get_developing_empty(app_and_developing):
    app, _ = app_and_developing
    async with await _client(app) as client:
        resp = await client.get("/api/v1/developing")
    assert resp.status_code == 200
    body = resp.json()
    assert body["seq"] == 0
    assert body["setups"] == []


async def test_get_developing_reflects_published_setups(app_and_developing):
    app, developing = app_and_developing
    setup = _sample_setup()
    assert setup is not None
    developing.publish([setup])

    async with await _client(app) as client:
        resp = await client.get("/api/v1/developing")
    body = resp.json()
    assert body["seq"] == 1
    assert body["setups"][0]["symbol"] == "BTCUSDT"
    assert body["setups"][0]["missing_conditions"] == ["spread"]
    assert "spread" in body["setups"][0]["projections"]


def test_ws_developing_sends_snapshot_on_connect():
    import asyncio

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    settings = Settings(control_token="ctrl", dashboard_unkill_token="unkill")
    kill_switch = KillSwitch(control_token="ctrl", unkill_token="unkill")
    developing = DevelopingSetupsService()
    setup = _sample_setup()
    assert setup is not None
    developing.publish([setup])
    app = create_app(
        engine=engine, settings=settings, kill_switch=kill_switch, developing_service=developing,
    )

    client = TestClient(app)
    with client.websocket_connect("/api/v1/stream/developing") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "snapshot"
    assert msg["setups"][0]["symbol"] == "BTCUSDT"
