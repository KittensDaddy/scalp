from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scalping.api.routers.scanner import serialize_scanner_row
from scalping.config.frozen import FrozenParams
from scalping.domain.models import BookTicker, RejectionReason, Side
from scalping.market_data.registry import SymbolStateRegistry
from scalping.scanner.service import ScannerRow

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def test_serialize_row_without_state_has_nulls():
    row = ScannerRow("BTCUSDT", Side.LONG, 80.0, True, None, None)
    out = serialize_scanner_row(row, None, now=NOW)
    assert out["symbol"] == "BTCUSDT"
    assert out["strategy"] == "caems_v2"
    assert out["preset"] is None
    assert out["price"] is None
    assert out["state"] == "ACCEPTED"
    assert out["reasons_top3"] == []


def test_serialize_row_includes_strategy_and_preset():
    row = ScannerRow(
        "SOLUSDT", Side.LONG, 70.0, True, None, None,
        strategy="ALT_RESIDUAL", preset="major_alt",
    )
    out = serialize_scanner_row(row, None, now=NOW)
    assert out["strategy"] == "ALT_RESIDUAL"
    assert out["preset"] == "major_alt"


def test_serialize_row_with_book_ticker_fills_price_and_spread():
    registry = SymbolStateRegistry(FrozenParams())
    bt = BookTicker(symbol="BTCUSDT", bid_price=99.9, bid_qty=1, ask_price=100.1, ask_qty=1, event_time=NOW)
    registry.on_book_ticker(bt)
    row = ScannerRow("BTCUSDT", Side.LONG, 80.0, True, None, None)
    out = serialize_scanner_row(row, registry.get("BTCUSDT"), now=NOW)
    assert out["price"] == bt.mid
    assert out["spread_bps"] == bt.spread_bps


def test_serialize_rejected_row_includes_reason():
    row = ScannerRow("BTCUSDT", Side.LONG, 0.0, False, RejectionReason.LOW_VOLUME, None)
    out = serialize_scanner_row(row, None, now=NOW)
    assert out["state"] == "REJECTED"
    assert out["reasons_top3"] == ["LOW_VOLUME"]


def test_age_ms_computed_from_last_kline_close():
    registry = SymbolStateRegistry(FrozenParams())
    from scalping.domain.models import Candle

    candle = Candle(
        symbol="BTCUSDT", timeframe="1m", open_time=NOW - timedelta(minutes=1), close_time=NOW,
        open=100, high=101, low=99, close=100.5, quote_volume=10,
    )
    registry.on_kline_1m_closed(candle)
    row = ScannerRow("BTCUSDT", Side.LONG, 80.0, True, None, None)
    out = serialize_scanner_row(row, registry.get("BTCUSDT"), now=NOW + timedelta(seconds=5))
    assert out["age_ms"] == 5000.0
