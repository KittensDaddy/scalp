from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from scalping.api.app import create_app
from scalping.config.settings import Settings
from scalping.exchanges.binance.selfcheck import SelfCheckResult, SelfCheckStepResult
from scalping.persistence.engine import init_db, make_engine
from scalping.persistence.models import RejectionRow, SignalRow
from scalping.persistence.selfcheck_repo import save_self_check
from scalping.risk.kill_switch import KillSwitch

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


@pytest.fixture
async def app_and_engine():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    settings = Settings(control_token="ctrl-token", dashboard_unkill_token="unkill-token")
    kill_switch = KillSwitch(control_token="ctrl-token", unkill_token="unkill-token")
    app = create_app(engine=engine, settings=settings, kill_switch=kill_switch)
    yield app, engine
    await engine.dispose()


async def _client(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_meta_endpoint(app_and_engine):
    app, _ = app_and_engine
    async with await _client(app) as client:
        resp = await client.get("/api/v1/meta")
    assert resp.status_code == 200
    body = resp.json()
    assert body["strategy_version"] == "caems_v2"
    assert len(body["config_hash"]) == 64


async def test_signals_endpoint_reflects_persisted_rows(app_and_engine):
    app, engine = app_and_engine
    sm = async_sessionmaker(engine)
    async with sm() as session:
        session.add(
            SignalRow(
                symbol="BTCUSDT", side="LONG", strategy_version="caems_v2",
                signal_time=NOW, entry_reference=100.0, stop=99.0, take_profit=101.35,
                strength=0.5, config_hash="abc",
            )
        )
        await session.commit()

    async with await _client(app) as client:
        resp = await client.get("/api/v1/signals")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["symbol"] == "BTCUSDT"


async def test_rejections_endpoint(app_and_engine):
    app, engine = app_and_engine
    sm = async_sessionmaker(engine)
    async with sm() as session:
        session.add(
            RejectionRow(
                symbol="ETHUSDT", side="SHORT", evaluated_at=NOW, strength=-0.1,
                reason="DEAD_BAND_TOO_SMALL", config_hash="abc",
            )
        )
        await session.commit()

    async with await _client(app) as client:
        resp = await client.get("/api/v1/rejections")
    body = resp.json()
    assert body[0]["reason"] == "DEAD_BAND_TOO_SMALL"


async def test_empty_placeholder_endpoints_return_correct_shape(app_and_engine):
    app, _ = app_and_engine
    async with await _client(app) as client:
        assert (await client.get("/api/v1/positions")).json() == []
        assert (await client.get("/api/v1/orders")).json() == []
        assert (await client.get("/api/v1/fills")).json() == []
        risk = (await client.get("/api/v1/risk")).json()
        assert risk["open_positions"] == 0


async def test_health_endpoint_reports_self_check_and_protection_gap(app_and_engine):
    app, engine = app_and_engine
    sm = async_sessionmaker(engine)
    async with sm() as session:
        await save_self_check(
            session,
            SelfCheckResult(
                checked_at=NOW, environment="testnet", passed=True,
                steps=[SelfCheckStepResult("algo_order_submit_cancel", True)],
            ),
        )
        await session.commit()

    async with await _client(app) as client:
        resp = await client.get("/api/v1/health")
    body = resp.json()
    assert body["self_check"]["passed"] is True
    assert body["protection_gap_ms"]["n"] == 0


async def test_kill_switch_requires_bearer_token(app_and_engine):
    app, _ = app_and_engine
    async with await _client(app) as client:
        resp = await client.post("/api/v1/control/kill-switch")
    assert resp.status_code == 401


async def test_kill_switch_engage_with_control_token(app_and_engine):
    app, _ = app_and_engine
    async with await _client(app) as client:
        resp = await client.post(
            "/api/v1/control/kill-switch", headers={"Authorization": "Bearer ctrl-token"}
        )
        assert resp.status_code == 200
        status = await client.get("/api/v1/control/kill-switch")
        assert status.json()["killed"] is True


async def test_kill_switch_clear_rejects_control_token(app_and_engine):
    app, _ = app_and_engine
    async with await _client(app) as client:
        await client.post(
            "/api/v1/control/kill-switch", headers={"Authorization": "Bearer ctrl-token"}
        )
        resp = await client.delete(
            "/api/v1/control/kill-switch", headers={"Authorization": "Bearer ctrl-token"}
        )
        assert resp.status_code == 401
        status = await client.get("/api/v1/control/kill-switch")
        assert status.json()["killed"] is True


async def test_kill_switch_clear_with_unkill_token_succeeds(app_and_engine):
    app, _ = app_and_engine
    async with await _client(app) as client:
        await client.post(
            "/api/v1/control/kill-switch", headers={"Authorization": "Bearer ctrl-token"}
        )
        resp = await client.delete(
            "/api/v1/control/kill-switch", headers={"Authorization": "Bearer unkill-token"}
        )
        assert resp.status_code == 200
        status = await client.get("/api/v1/control/kill-switch")
        assert status.json()["killed"] is False


async def test_cors_locked_to_dashboard_origin(app_and_engine):
    app, _ = app_and_engine
    async with await _client(app) as client:
        resp = await client.get(
            "/api/v1/meta", headers={"Origin": "http://localhost:5173"}
        )
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"

    async with await _client(app) as client:
        resp = await client.get(
            "/api/v1/meta", headers={"Origin": "http://evil.example.com"}
        )
    assert "access-control-allow-origin" not in resp.headers
