from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scalping.config.frozen import FrozenParams
from scalping.domain.models import BookTicker, Candle
from scalping.market_data.registry import SymbolStateRegistry
from scalping.market_data.staleness import Feed

T0 = datetime(2026, 8, 9, 0, 0, tzinfo=UTC)


def _candle(i: int) -> Candle:
    return Candle(
        symbol="BTCUSDT", timeframe="1m",
        open_time=T0 + timedelta(minutes=i), close_time=T0 + timedelta(minutes=i + 1),
        open=100.0, high=100.5, low=99.5, close=100.0 + i * 0.01, quote_volume=100.0 + i,
    )


def test_book_ticker_updates_state_and_staleness():
    registry = SymbolStateRegistry(FrozenParams())
    bt = BookTicker(symbol="BTCUSDT", bid_price=99.9, bid_qty=1, ask_price=100.1, ask_qty=1, event_time=T0)
    registry.on_book_ticker(bt)
    state = registry.get("BTCUSDT")
    assert state is not None
    assert state.last_book_ticker == bt
    assert registry.staleness.is_stale("BTCUSDT", Feed.BOOK_TICKER, T0) is False


def test_kline_1m_updates_indicators_incrementally():
    registry = SymbolStateRegistry(FrozenParams())
    for i in range(50):
        registry.on_kline_1m_closed(_candle(i))
    state = registry.get("BTCUSDT")
    assert state.ema_fast_1m.ready is True
    assert state.atr_1m.ready is True
    assert state.last_kline_1m_close_time == _candle(49).close_time


def test_volume_median_returned_is_prior_state_not_including_current_bar():
    registry = SymbolStateRegistry(FrozenParams())
    medians = [registry.on_kline_1m_closed(_candle(i)) for i in range(5)]
    assert medians[0] is None  # nothing recorded yet before first bar


def test_unknown_symbol_returns_none():
    registry = SymbolStateRegistry(FrozenParams())
    assert registry.get("NOPE") is None


def test_symbols_lists_all_seen_symbols():
    registry = SymbolStateRegistry(FrozenParams())
    registry.on_kline_1m_closed(_candle(0))
    bt = BookTicker(symbol="ETHUSDT", bid_price=1, bid_qty=1, ask_price=1.01, ask_qty=1, event_time=T0)
    registry.on_book_ticker(bt)
    assert set(registry.symbols()) == {"BTCUSDT", "ETHUSDT"}
