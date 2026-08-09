"""`/evidence` and the campaign reads behind it.

The bar is pre-registered (PLAN §8) and this is the only thing allowed to say
"go", so the tests care most about what it refuses to claim.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from scalping.api.app import create_app
from scalping.config.settings import EffectiveConfig, Settings
from scalping.domain.models import EntryOutcome
from scalping.edge.campaign import OpsAttestation, build_campaign_evidence
from scalping.persistence.campaign_repo import (
    load_drawdown_snapshot,
    load_markouts_by_entry_type,
)
from scalping.persistence.engine import init_db, make_engine
from scalping.persistence.models import EntryAttemptRow, TradeRow
from scalping.risk.kill_switch import KillSwitch

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)  # a Wednesday


@pytest.fixture
async def engine():
    eng = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(eng)
    yield eng
    await eng.dispose()


def _app(engine):
    settings = Settings(control_token="ctrl", dashboard_unkill_token="unkill")
    return create_app(
        engine=engine,
        settings=settings,
        kill_switch=KillSwitch(control_token="ctrl", unkill_token="unkill"),
    )


async def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _trade(i: int, r: float, closed_at: datetime) -> TradeRow:
    return TradeRow(
        trade_id=f"t{i}",
        strategy_version="caems_v2",
        symbol="BTCUSDT",
        side="LONG",
        entry_price=100.0,
        exit_price=101.0,
        quantity=0.1,
        r_multiple=r,
        opened_at=closed_at.replace(tzinfo=None),
        closed_at=closed_at.replace(tzinfo=None),
        exit_reason="TAKE_PROFIT_MARKET",
        config_hash="cfg",
    )


def _attempt(i: int, outcome: EntryOutcome, markout: float | None) -> EntryAttemptRow:
    return EntryAttemptRow(
        symbol="BTCUSDT",
        side="LONG",
        outcome=outcome.value,
        attempted_at=NOW.replace(tzinfo=None),
        fill_price=100.0,
        markout_30s_bps=markout,
        config_hash="cfg",
    )


async def test_evidence_endpoint_reports_all_eight_criteria(engine):
    async with await _client(_app(engine)) as client:
        resp = await client.get("/api/v1/evidence")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["criteria"]) == 8
    assert body["passed"] is False  # empty campaign


async def test_empty_campaign_fails_rather_than_erroring(engine):
    async with await _client(_app(engine)) as client:
        body = (await client.get("/api/v1/evidence")).json()

    by_name = {c["name"]: c for c in body["criteria"]}
    assert by_name["sample_size"]["passed"] is False
    assert by_name["protection_gap"]["passed"] is False
    assert body["sample"]["n_trades"] == 0


async def test_unmeasured_protection_gap_does_not_pass(engine):
    """No samples means unmeasured, not fast. A flattering default here would
    let the campaign clear a safety criterion it never tested."""
    async with async_sessionmaker(engine)() as session:
        campaign = await build_campaign_evidence(
            session, config=EffectiveConfig(), n_bootstrap=200
        )

    gap = next(c for c in campaign.report.criteria if c.name == "protection_gap")
    assert gap.passed is False
    assert campaign.protection_gap_p99_ms is None


async def test_paper_data_alone_cannot_pass_the_bar(engine):
    """A great paper sample still fails on the testnet-only criteria."""
    async with async_sessionmaker(engine)() as session:
        for i in range(320):
            session.add(_trade(i, 1.35 if i % 2 else -1.0, NOW))
        for i in range(600):
            session.add(_attempt(i, EntryOutcome.MAKER_FILL, -1.0))
        await session.commit()

    async with await _client(_app(engine)) as client:
        body = (await client.get("/api/v1/evidence")).json()

    by_name = {c["name"]: c for c in body["criteria"]}
    assert by_name["sample_size"]["passed"] is True
    assert by_name["reconciliation"]["passed"] is False
    assert by_name["kill_switch_verified"]["passed"] is False
    assert body["passed"] is False


async def test_ops_attestation_can_supply_the_testnet_criteria(engine):
    async with await _client(_app(engine)) as client:
        body = (
            await client.get(
                "/api/v1/evidence",
                params={
                    "clean_restarts": 3,
                    "clean_disconnects": 3,
                    "kill_switch_verified": True,
                },
            )
        ).json()

    by_name = {c["name"]: c for c in body["criteria"]}
    assert by_name["reconciliation"]["passed"] is True
    assert by_name["kill_switch_verified"]["passed"] is True


async def test_maker_taker_decision_uses_recorded_markouts(engine):
    async with async_sessionmaker(engine)() as session:
        for i in range(200):
            session.add(_attempt(i, EntryOutcome.MAKER_FILL, -8.0))
        for i in range(200):
            session.add(_attempt(1000 + i, EntryOutcome.TAKER_CONVERT, 1.0))
        await session.commit()

        campaign = await build_campaign_evidence(
            session, config=EffectiveConfig(), n_bootstrap=200
        )

    # Maker markouts far worse than taker, beyond the 3bps fee difference.
    assert campaign.maker_taker.resolved is True
    assert campaign.maker_taker.switch_to_taker is True


async def test_attempts_without_markouts_are_excluded_not_zeroed(engine):
    async with async_sessionmaker(engine)() as session:
        session.add(_attempt(1, EntryOutcome.MAKER_FILL, None))
        session.add(_attempt(2, EntryOutcome.MAKER_FILL, -4.0))
        await session.commit()

        sample = await load_markouts_by_entry_type(session)

    assert sample.maker_30s_bps == [-4.0]


async def test_abandoned_attempts_are_in_neither_markout_arm(engine):
    async with async_sessionmaker(engine)() as session:
        session.add(_attempt(1, EntryOutcome.ABANDONED, 2.0))
        await session.commit()

        sample = await load_markouts_by_entry_type(session)

    assert sample.n == 0


async def test_drawdown_snapshot_restores_daily_and_weekly_r(engine):
    """A restart must not hand the strategy a fresh loss budget mid-campaign."""
    async with async_sessionmaker(engine)() as session:
        session.add(_trade(1, -1.0, NOW))  # today
        session.add(_trade(2, -0.5, NOW - timedelta(days=1)))  # earlier this week
        session.add(_trade(3, -9.0, NOW - timedelta(days=10)))  # a previous week
        await session.commit()

        snap = await load_drawdown_snapshot(session, now=NOW)

    assert snap.daily_r == pytest.approx(-1.0)
    assert snap.weekly_r == pytest.approx(-1.5)
    assert len(snap.trade_r_history) == 2


async def test_ops_attestation_defaults_to_unverified():
    ops = OpsAttestation()
    assert ops.clean_restarts == 0
    assert ops.clean_disconnects == 0
    assert ops.kill_switch_verified is False
