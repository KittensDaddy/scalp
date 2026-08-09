"""A dead feed must suppress signals rather than trade on a frozen book.

`StalenessWatchdog` existed and was unit-tested from the start, but the live
`build_eval_context` hardcoded `stale=False`, so nothing ever consulted it. The
symptom is silent: the last book stays in place, the scanner keeps showing a
price, and only the fills reveal it was hours old.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scalping.config.frozen import FrozenParams
from scalping.config.settings import EffectiveConfig
from scalping.domain.models import BookTicker, Candle, RejectionReason
from scalping.market_data.registry import SymbolStateRegistry
from scalping.market_data.staleness import Feed, StalenessWatchdog
from scalping.runtime.context import build_eval_context

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def _warm_registry(registry: SymbolStateRegistry, symbol: str, at: datetime) -> None:
    """Feed enough closed candles that the indicators report ready.

    The 5m slow EMA has period 50, so it needs its own run of 5m candles — 60 1m
    bars aggregate to only 12.
    """
    price = 100.0
    for i in range(80):
        ts = at - timedelta(minutes=80 - i)
        registry.on_kline_1m_closed(
            Candle(
                symbol=symbol, timeframe="1m", open_time=ts, close_time=ts + timedelta(minutes=1),
                open=price, high=price + 0.5, low=price - 0.5, close=price, quote_volume=1000.0,
            )
        )
        price += 0.05

    price = 100.0
    for i in range(80):
        ts = at - timedelta(minutes=5 * (80 - i))
        registry.on_kline_5m_closed(
            Candle(
                symbol=symbol, timeframe="5m", open_time=ts, close_time=ts + timedelta(minutes=5),
                open=price, high=price + 0.5, low=price - 0.5, close=price, quote_volume=5000.0,
            )
        )
        price += 0.25


def _registry_with_book(book_time: datetime) -> SymbolStateRegistry:
    registry = SymbolStateRegistry(FrozenParams(), staleness=StalenessWatchdog())
    _warm_registry(registry, "BTCUSDT", NOW)
    registry.on_book_ticker(
        BookTicker(
            symbol="BTCUSDT", bid_price=100.0, bid_qty=5.0,
            ask_price=100.02, ask_qty=5.0, event_time=book_time,
        )
    )
    return registry


def test_fresh_book_is_not_flagged_stale():
    registry = _registry_with_book(NOW)
    ctx = build_eval_context(
        registry.get("BTCUSDT"), config=EffectiveConfig(), evaluated_at=NOW,
        staleness=registry.staleness,
    )
    assert ctx is not None
    assert ctx.flags.stale_market_data is False


def test_old_book_is_flagged_stale():
    """Book last seen 60s ago, well past the 5s bookTicker budget."""
    registry = _registry_with_book(NOW - timedelta(seconds=60))
    ctx = build_eval_context(
        registry.get("BTCUSDT"), config=EffectiveConfig(), evaluated_at=NOW,
        staleness=registry.staleness,
    )
    assert ctx is not None
    assert ctx.flags.stale_market_data is True


def test_stale_flag_reaches_both_sides_feature_inputs():
    registry = _registry_with_book(NOW - timedelta(seconds=60))
    ctx = build_eval_context(
        registry.get("BTCUSDT"), config=EffectiveConfig(), evaluated_at=NOW,
        staleness=registry.staleness,
    )
    assert all(raw.stale for raw in ctx.feature_raw_by_side.values())


def test_stale_market_data_rejects_the_signal():
    """The whole point: a frozen feed produces STALE_MARKET_DATA, not a trade."""
    from scalping.strategies.caems.engine import evaluate

    registry = _registry_with_book(NOW - timedelta(seconds=60))
    ctx = build_eval_context(
        registry.get("BTCUSDT"), config=EffectiveConfig(), evaluated_at=NOW,
        staleness=registry.staleness,
    )
    for side, raw in ctx.feature_raw_by_side.items():
        evaluation, signal = evaluate(
            side=side, snapshot=ctx.snapshot, config=EffectiveConfig(),
            frozen=FrozenParams(), config_hash="h", evaluated_at=NOW,
            flags=ctx.flags, risk_cost=ctx.risk_cost_by_side[side],
        )
        assert evaluation.accepted is False
        assert evaluation.rejection_reason == RejectionReason.STALE_MARKET_DATA
        assert signal is None
        assert raw.stale is True


def test_no_watchdog_supplied_keeps_previous_behaviour():
    """Callers that don't track staleness (tests, replay) are unaffected."""
    registry = _registry_with_book(NOW - timedelta(hours=5))
    ctx = build_eval_context(
        registry.get("BTCUSDT"), config=EffectiveConfig(), evaluated_at=NOW
    )
    assert ctx.flags.stale_market_data is False


def test_watchdog_reports_age_for_health_readout():
    registry = _registry_with_book(NOW - timedelta(seconds=12))
    age = registry.staleness.data_age_ms("BTCUSDT", Feed.BOOK_TICKER, NOW)
    assert age == 12_000.0
