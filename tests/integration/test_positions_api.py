from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from scalping.api.app import create_app
from scalping.api.routers.positions import serialize_active_trade
from scalping.config.settings import Settings
from scalping.domain.models import Position, Side
from scalping.monitoring.active_trades import ActiveTradeService
from scalping.persistence.engine import init_db, make_engine
from scalping.risk.kill_switch import KillSwitch

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def _position() -> Position:
    return Position(
        symbol="SOLUSDT",
        side=Side.LONG,
        entry_price=184.20,
        quantity=10.0,
        stop_price=183.61,
        take_profit_price=185.62,
        opened_at=NOW,
    )


@pytest.fixture
async def app_and_active():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    settings = Settings(control_token="ctrl", dashboard_unkill_token="unkill")
    kill_switch = KillSwitch(control_token="ctrl", unkill_token="unkill")
    active = ActiveTradeService()
    app = create_app(
        engine=engine, settings=settings, kill_switch=kill_switch,
        active_trades_service=active,
    )
    yield app, active
    await engine.dispose()


async def _client(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_get_positions_empty(app_and_active):
    app, _ = app_and_active
    async with await _client(app) as client:
        resp = await client.get("/api/v1/positions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["seq"] == 0
    assert body["positions"] == []


async def test_get_positions_and_timeline_after_paper_lifecycle(app_and_active):
    app, active = app_and_active
    active.open_trade(trade_id="paper-1", position=_position(), score=91.0, ts=NOW)
    active.mark_protected("paper-1", ts=NOW, t_protection_ms=110.0)
    active.update_price("paper-1", 184.50)
    active.move_breakeven("paper-1", new_stop=184.20, ts=NOW)
    active.update_score("paper-1", score=84.0, ts=NOW, explanation="spread widened")
    active.close_trade(
        "paper-1", exit_price=185.62, exit_reason="TAKE_PROFIT", ts=NOW
    )

    async with await _client(app) as client:
        positions = (await client.get("/api/v1/positions")).json()
        assert positions["positions"] == []  # closed — not in open set
        risk = (await client.get("/api/v1/risk")).json()
        assert risk["open_positions"] == 0

        events = (await client.get("/api/v1/positions/paper-1/events")).json()

    assert [e["event_type"] for e in events["events"]] == [
        "OPENED", "PROTECTED", "BREAKEVEN_MOVED", "SCORE_CHANGED", "CLOSED",
    ]
    # hard constraint: no probability fields anywhere in the timeline payloads
    blob = str(events)
    assert "probability" not in blob.lower()
    assert "win_rate" not in blob.lower()


async def test_open_position_reflected_in_risk(app_and_active):
    app, active = app_and_active
    active.open_trade(trade_id="paper-1", position=_position(), ts=NOW)

    async with await _client(app) as client:
        body = (await client.get("/api/v1/positions")).json()
        risk = (await client.get("/api/v1/risk")).json()

    assert len(body["positions"]) == 1
    assert body["positions"][0]["symbol"] == "SOLUSDT"
    assert body["positions"][0]["health"] in {
        "HEALTHY", "AT_RISK", "NEAR_STOP", "NEAR_TP",
    }
    assert "probability" not in body["positions"][0]
    assert risk["open_positions"] == 1


def test_serialize_active_trade_has_no_probability_keys():
    service = ActiveTradeService()
    trade, _, _ = service.open_trade(trade_id="t1", position=_position(), ts=NOW)
    body = serialize_active_trade(trade)
    assert body["health"] == "HEALTHY"
    for key in body:
        assert "probabilit" not in key.lower()
        assert "win_rate" not in key.lower()
        assert "chance" not in key.lower()


def test_ws_positions_sends_snapshot_on_connect():
    import asyncio

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    settings = Settings(control_token="ctrl", dashboard_unkill_token="unkill")
    kill_switch = KillSwitch(control_token="ctrl", unkill_token="unkill")
    active = ActiveTradeService()
    active.open_trade(trade_id="t1", position=_position(), ts=NOW)
    app = create_app(
        engine=engine, settings=settings, kill_switch=kill_switch,
        active_trades_service=active,
    )

    client = TestClient(app)
    with client.websocket_connect("/api/v1/stream/positions") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "snapshot"
    assert msg["positions"][0]["symbol"] == "SOLUSDT"
    assert msg["positions"][0]["health"] == "HEALTHY"
