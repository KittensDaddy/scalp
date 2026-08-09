"""Integration: analytics + calibration + lab presets APIs."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from scalping.api.app import create_app
from scalping.config.settings import Settings
from scalping.persistence.engine import init_db, make_engine
from scalping.persistence.models import CalibrationStatsRow, PresetRow, TradeRow
from scalping.risk.kill_switch import KillSwitch

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


@pytest.fixture
async def app_engine():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    settings = Settings(control_token="ctrl", dashboard_unkill_token="unkill")
    kill_switch = KillSwitch(control_token="ctrl", unkill_token="unkill")
    app = create_app(engine=engine, settings=settings, kill_switch=kill_switch)
    yield app, engine
    await engine.dispose()


async def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_analytics_groups_persisted_trades(app_engine):
    app, engine = app_engine
    sm = async_sessionmaker(engine)
    async with sm() as session:
        for i, (sym, r) in enumerate([("BTCUSDT", 1.0), ("BTCUSDT", -1.0), ("ETHUSDT", 0.5)]):
            session.add(
                TradeRow(
                    trade_id=f"t{i}", strategy_version="caems_v2", symbol=sym, side="LONG",
                    entry_price=100.0, exit_price=101.0, quantity=1.0, r_multiple=r,
                    opened_at=NOW, closed_at=NOW, exit_reason="TAKE_PROFIT",
                    config_hash="abc", mae=0.2, mfe=1.0,
                )
            )
        await session.commit()

    async with await _client(app) as client:
        resp = await client.get("/api/v1/analytics?group_by=symbol")
    assert resp.status_code == 200
    body = resp.json()
    assert body["n_trades"] == 3
    keys = {g["key"] for g in body["groups"]}
    assert keys == {"BTCUSDT", "ETHUSDT"}


async def test_calibration_gates_probability(app_engine):
    app, engine = app_engine
    sm = async_sessionmaker(engine)
    async with sm() as session:
        session.add(
            CalibrationStatsRow(
                strategy_version="caems_v2", side="LONG", regime="trend_up",
                score_bucket="70-80", n=10, wins=7, sum_r=3.0,
                updated_at=NOW.replace(tzinfo=None),
            )
        )
        session.add(
            CalibrationStatsRow(
                strategy_version="caems_v2", side="LONG", regime="trend_up",
                score_bucket="80-90", n=40, wins=24, sum_r=8.0,
                updated_at=NOW.replace(tzinfo=None),
            )
        )
        await session.commit()

    async with await _client(app) as client:
        resp = await client.get("/api/v1/calibration?min_samples=30")
    body = resp.json()
    by_bucket = {b["score_bucket"]: b["probability"] for b in body["buckets"]}
    assert by_bucket["70-80"]["available"] is False
    assert by_bucket["70-80"]["win_probability"] is None
    assert by_bucket["80-90"]["available"] is True
    assert by_bucket["80-90"]["win_probability"] == pytest.approx(0.6)


async def test_preset_version_and_paper_activate(app_engine):
    app, _engine = app_engine
    headers = {"Authorization": "Bearer ctrl"}
    async with await _client(app) as client:
        resp = await client.post(
            "/api/v1/presets/meme/versions",
            headers=headers,
            json={"params": {"spread_max_bps": 3.0, "rvol_min": 2.0}, "author": "test"},
        )
        assert resp.status_code == 200
        assert resp.json()["version"] == 1

        # frozen key refused
        bad = await client.post(
            "/api/v1/presets/meme/versions",
            headers=headers,
            json={"params": {"ema_fast_1m": 9}},
        )
        assert bad.status_code == 400

        act = await client.post(
            "/api/v1/presets/meme/activate",
            headers=headers,
            json={"version": 1},
        )
        assert act.status_code == 200
        assert act.json()["activated"] == "paper"

        eff = await client.get("/api/v1/presets/meme/effective?symbol=DOGEUSDT")
        assert eff.status_code == 200
        assert any(p["key"] == "spread_max_bps" for p in eff.json()["provenance"])


async def test_enqueue_backtest_and_complete(app_engine):
    app, _engine = app_engine
    from datetime import timedelta

    from scalping.domain.models import Candle
    from scalping.lab.backtest_jobs import BacktestJobStatus

    async def loader(symbols, date_from, date_to):
        c1 = []
        t0 = NOW
        for i in range(10):
            ts = t0 + timedelta(minutes=i)
            c1.append(
                Candle(
                    symbol="BTCUSDT",
                    timeframe="1m",
                    open_time=ts,
                    close_time=ts + timedelta(minutes=1),
                    open=100.0,
                    high=101.0,
                    low=99.0,
                    close=100.5,
                    quote_volume=1_000_000.0,
                )
            )
        return c1, c1[:2]

    app.state.scalping.candle_loader = loader
    runner = app.state.scalping.backtest_runner
    await runner.start()
    headers = {"Authorization": "Bearer ctrl"}
    async with await _client(app) as client:
        await client.post(
            "/api/v1/presets/meme/versions",
            headers=headers,
            json={"params": {"spread_max_bps": 3.0}, "author": "test"},
        )
        resp = await client.post(
            "/api/v1/backtests",
            headers=headers,
            json={
                "preset_id": "meme",
                "preset_version": 1,
                "symbols": ["BTCUSDT"],
                "date_from": NOW.isoformat(),
                "date_to": (NOW + timedelta(hours=1)).isoformat(),
                "mode": "CANDLE",
            },
        )
        assert resp.status_code == 200, resp.text
        job_id = resp.json()["job_id"]

        import asyncio

        for _ in range(50):
            job = runner.get(job_id)
            assert job is not None
            if job.status in (BacktestJobStatus.COMPLETED, BacktestJobStatus.FAILED):
                break
            await asyncio.sleep(0.05)
        job = runner.get(job_id)
        assert job is not None
        assert job.status is BacktestJobStatus.COMPLETED
        assert job.result is not None
        assert "banner" in job.result

        got = await client.get(f"/api/v1/backtests/{job_id}")
        assert got.status_code == 200
        assert got.json()["status"] == "COMPLETED"
    await runner.stop()


async def test_live_activate_requires_confirm_and_gates(app_engine):
    app, engine = app_engine
    sm = async_sessionmaker(engine)
    async with sm() as session:
        session.add(
            PresetRow(
                preset_id="meme", name="meme", version=1, class_rule={},
                params={"spread_max_bps": 3.0}, overlay=False, disabled=False,
                created_at=NOW.replace(tzinfo=None), author="t", note="",
                activated_paper=True, activated_live=False,
            )
        )
        await session.commit()

    headers = {"Authorization": "Bearer ctrl"}
    async with await _client(app) as client:
        no_confirm = await client.post(
            "/api/v1/presets/meme/activate-live",
            headers=headers,
            json={"version": 1, "confirm": False},
        )
        assert no_confirm.status_code == 400
        blocked = await client.post(
            "/api/v1/presets/meme/activate-live",
            headers=headers,
            json={"version": 1, "confirm": True},
        )
        assert blocked.status_code == 409
