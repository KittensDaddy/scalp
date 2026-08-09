"""The campaign-evidence duties the paper executor carries alongside execution:
markouts written back to entry attempts, cooldowns set on close, and every close
path reaching the drawdown machine.

Each of these was implemented-but-unwired at the readiness audit — the module
existed and was unit-tested, nothing in `--run` ever called it. These tests pin
the wiring, not the arithmetic.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from scalping.config.settings import CooldownConfig, EffectiveConfig
from scalping.domain.models import BookTicker, EntryOutcome, Side, SignalCandidate
from scalping.monitoring.active_trades import ActiveTradeService
from scalping.paper.venue import PaperVenue
from scalping.persistence.engine import init_db, make_engine
from scalping.persistence.models import CooldownRow, EntryAttemptRow
from scalping.runtime.paper_executor import PaperExecutor
from scalping.scanner.cooldowns import CooldownManager

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


@pytest.fixture
async def sessionmaker():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    sm = async_sessionmaker(engine)
    yield sm
    await engine.dispose()


def _bt(bid: float, ask: float, symbol: str = "BTCUSDT") -> BookTicker:
    return BookTicker(
        symbol=symbol, bid_price=bid, bid_qty=10.0, ask_price=ask, ask_qty=10.0, event_time=NOW
    )


def _signal(symbol: str = "BTCUSDT") -> SignalCandidate:
    return SignalCandidate(
        symbol=symbol,
        side=Side.LONG,
        strategy_version="caems_v2",
        signal_time=NOW,
        entry_reference=100.0,
        stop=99.0,
        take_profit=101.35,
        strength=0.5,
        config_hash="abc",
    )


def _executor(venue, active, sessionmaker=None, **kwargs) -> PaperExecutor:
    # No real waiting: markout offsets are driven by an injected sleep.
    kwargs.setdefault("sleep", _instant_sleep)
    return PaperExecutor(
        venue=venue,
        active_trades=active,
        config=EffectiveConfig(),
        entry_ttl_s=0.01,
        sessionmaker=sessionmaker,
        config_hash="cfg",
        **kwargs,
    )


async def _instant_sleep(_delay: float) -> None:
    await asyncio.sleep(0)


async def _drain() -> None:
    for _ in range(20):
        await asyncio.sleep(0.01)


async def test_markouts_are_recorded_for_a_fill(sessionmaker):
    venue = PaperVenue()
    venue.on_book_ticker(_bt(100.0, 100.1))
    active = ActiveTradeService()
    ex = _executor(venue, active, sessionmaker)

    await ex.on_signals([_signal()], NOW)
    await _drain()
    # Price drifts up after the fill — a favourable markout for a long.
    venue.on_book_ticker(_bt(100.5, 100.6))
    await _drain()

    async with sessionmaker() as session:
        rows = (await session.execute(select(EntryAttemptRow))).scalars().all()

    assert len(rows) == 1
    row = rows[0]
    assert row.markout_5s_bps is not None, "5s markout never written"
    assert row.markout_30s_bps is not None, "30s markout never written"
    assert row.markout_5s_r is not None
    assert row.markout_30s_r is not None


async def test_markout_sign_follows_position_direction(sessionmaker):
    venue = PaperVenue()
    venue.on_book_ticker(_bt(100.0, 100.1))
    active = ActiveTradeService()
    ex = _executor(venue, active, sessionmaker)

    await ex.on_signals([_signal()], NOW)
    await _drain()
    venue.on_book_ticker(_bt(90.0, 90.1))  # long, price collapses
    await _drain()

    async with sessionmaker() as session:
        row = (await session.execute(select(EntryAttemptRow))).scalars().one()

    assert row.markout_30s_bps < 0


async def test_entry_attempt_outcome_is_persisted_for_the_decision_rule(sessionmaker):
    venue = PaperVenue()
    venue.on_book_ticker(_bt(100.0, 100.1))
    active = ActiveTradeService()
    ex = _executor(venue, active, sessionmaker)

    await ex.on_signals([_signal()], NOW)
    await _drain()

    async with sessionmaker() as session:
        row = (await session.execute(select(EntryAttemptRow))).scalars().one()

    assert row.outcome in {o.value for o in EntryOutcome}


async def test_close_sets_and_persists_a_symbol_cooldown(sessionmaker):
    venue = PaperVenue()
    venue.on_book_ticker(_bt(100.0, 100.1))
    active = ActiveTradeService()
    cooldowns = CooldownManager()
    ex = _executor(venue, active, sessionmaker, cooldowns=cooldowns)

    await ex.on_signals([_signal()], NOW)
    await _drain()
    # Stop triggers.
    venue.on_book_ticker(_bt(98.0, 98.1))
    await ex.sync_closes(NOW)

    assert cooldowns.is_active("symbol", "BTCUSDT", NOW) is True
    async with sessionmaker() as session:
        rows = (await session.execute(select(CooldownRow))).scalars().all()
    assert [r.key for r in rows] == ["BTCUSDT"]


async def test_losing_trade_cools_down_longer_than_a_winner():
    venue = PaperVenue()
    venue.on_book_ticker(_bt(100.0, 100.1))
    active = ActiveTradeService()
    cooldowns = CooldownManager()
    config = EffectiveConfig(cooldowns=CooldownConfig(post_trade_s=60.0, post_loss_s=600.0))
    ex = PaperExecutor(
        venue=venue,
        active_trades=active,
        config=config,
        entry_ttl_s=0.01,
        cooldowns=cooldowns,
        sleep=_instant_sleep,
    )

    await ex._apply_close_cooldown("BTCUSDT", -1.0, NOW)
    loss_until = cooldowns.active_cooldown("symbol", "BTCUSDT", NOW).until
    cooldowns.clear("symbol", "BTCUSDT")
    await ex._apply_close_cooldown("ETHUSDT", 1.4, NOW)
    win_until = cooldowns.active_cooldown("symbol", "ETHUSDT", NOW).until

    assert loss_until > win_until


async def test_closed_trade_reaches_the_drawdown_machine():
    venue = PaperVenue()
    venue.on_book_ticker(_bt(100.0, 100.1))
    active = ActiveTradeService()
    ex = _executor(venue, active)

    await ex.on_signals([_signal()], NOW)
    await _drain()
    venue.on_book_ticker(_bt(98.0, 98.1))
    await ex.sync_closes(NOW)

    assert ex.risk.drawdown.trade_r_history, "close never recorded against drawdown"
    assert ex.risk.drawdown.daily_r < 0


async def test_protection_failure_close_also_reaches_the_drawdown_machine():
    """The protection-timeout path closes a real trade and must not bypass the
    loss budget — it is exactly the failure mode the budget exists for."""

    class FailingProtection(PaperVenue):
        async def place_stop(self, *a, **kw):
            raise RuntimeError("algo endpoint down")

    venue = FailingProtection()
    venue.on_book_ticker(_bt(100.0, 100.1))
    active = ActiveTradeService()
    cooldowns = CooldownManager()
    ex = _executor(venue, active, cooldowns=cooldowns)

    await ex.on_signals([_signal()], NOW)
    await _drain()

    assert ex.risk.drawdown.trade_r_history, "protection-timeout close skipped drawdown"
    assert cooldowns.is_active("symbol", "BTCUSDT", NOW) is True


async def test_exit_is_priced_at_the_trigger_fill_not_the_last_mark():
    """R is the campaign's whole evidence base. Booking the exit at a stale mark
    understates a stop-out by however far price moved since the last tick."""
    venue = PaperVenue()
    venue.on_book_ticker(_bt(100.0, 100.1))
    active = ActiveTradeService()
    ex = _executor(venue, active)

    await ex.on_signals([_signal()], NOW)
    await _drain()
    trade_id = next(iter(ex._symbol_to_trade.values()))
    # Last mark taken well above the stop, then price gaps straight through it.
    active.update_price(trade_id, 100.0)
    venue.on_book_ticker(_bt(95.0, 95.1))
    await ex.sync_closes(NOW)

    closed = active.get(trade_id)
    assert closed.current_price == 95.0
    assert closed.exit_reason == "STOP_MARKET"
    # Priced off the actual fill: (95 - entry) / (entry - 99). Pricing it at the
    # stale 100.0 mark would have booked roughly 0R for a multi-R loss.
    expected_r = (95.0 - closed.entry_price) / (closed.entry_price - 99.0)
    assert closed.unrealized_r == pytest.approx(expected_r)
    assert closed.unrealized_r < -4.0
