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
from scalping.scanner.service import ScannerRow, ScannerService

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


@pytest.fixture
async def app_and_scanner():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    settings = Settings(control_token="ctrl", dashboard_unkill_token="unkill")
    kill_switch = KillSwitch(control_token="ctrl", unkill_token="unkill")
    scanner = ScannerService()
    app = create_app(engine=engine, settings=settings, kill_switch=kill_switch, scanner_service=scanner)
    yield app, scanner
    await engine.dispose()


async def _client(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_get_scanner_empty(app_and_scanner):
    app, _ = app_and_scanner
    async with await _client(app) as client:
        resp = await client.get("/api/v1/scanner")
    assert resp.status_code == 200
    body = resp.json()
    assert body["seq"] == 0
    assert body["rows"] == []


async def test_get_scanner_reflects_published_rows(app_and_scanner):
    app, scanner = app_and_scanner
    scanner.publish([ScannerRow("BTCUSDT", Side.LONG, 87.0, True, None, None)])

    async with await _client(app) as client:
        resp = await client.get("/api/v1/scanner")
    body = resp.json()
    assert body["seq"] == 1
    assert body["rows"][0]["symbol"] == "BTCUSDT"
    assert body["rows"][0]["score"] == 87.0


async def test_get_symbol_detail_for_known_symbol(app_and_scanner):
    app, scanner = app_and_scanner
    scanner.publish([ScannerRow("ETHUSDT", Side.SHORT, 42.0, True, None, None)])

    async with await _client(app) as client:
        resp = await client.get("/api/v1/symbol/ETHUSDT")
    body = resp.json()
    assert body["symbol"] == "ETHUSDT"
    assert body["row"]["score"] == 42.0


async def test_get_symbol_detail_for_unknown_symbol(app_and_scanner):
    app, _ = app_and_scanner
    async with await _client(app) as client:
        resp = await client.get("/api/v1/symbol/NOPEUSDT")
    body = resp.json()
    assert body["row"] is None
    assert body["why_not"] == []


def test_ws_scanner_sends_snapshot_on_connect():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    import asyncio

    asyncio.run(init_db(engine))
    settings = Settings(control_token="ctrl", dashboard_unkill_token="unkill")
    kill_switch = KillSwitch(control_token="ctrl", unkill_token="unkill")
    scanner = ScannerService()
    scanner.publish([ScannerRow("BTCUSDT", Side.LONG, 90.0, True, None, None)])
    app = create_app(engine=engine, settings=settings, kill_switch=kill_switch, scanner_service=scanner)

    client = TestClient(app)
    with client.websocket_connect("/api/v1/stream/scanner") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "snapshot"
    assert msg["rows"][0]["symbol"] == "BTCUSDT"


def test_ws_positions_and_system_streams_accept_connections():
    """Delta forwarding itself is covered by `test_broadcaster.py` in a single
    event loop; here we only prove the WS routes exist, accept a connection, and
    don't error before any message is published (Starlette's TestClient runs the
    ASGI app on a separate thread/event loop, so publishing into a subscriber's
    asyncio.Queue from the test's own loop is a cross-loop hazard best avoided)."""
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    import asyncio

    asyncio.run(init_db(engine))
    settings = Settings(control_token="ctrl", dashboard_unkill_token="unkill")
    kill_switch = KillSwitch(control_token="ctrl", unkill_token="unkill")
    app = create_app(engine=engine, settings=settings, kill_switch=kill_switch)

    client = TestClient(app)
    with client.websocket_connect("/api/v1/stream/positions"):
        pass
    with client.websocket_connect("/api/v1/stream/system"):
        pass
