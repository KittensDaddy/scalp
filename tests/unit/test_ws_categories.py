from __future__ import annotations

import pytest

from scalping.exchanges.base.errors import WebSocketCategoryMixError
from scalping.exchanges.binance.ws import (
    BinanceWSConnection,
    StreamCategory,
    validate_single_category,
)


def test_bookticker_streams_are_public():
    cat = validate_single_category(["btcusdt@bookTicker", "ethusdt@bookTicker"])
    assert cat == StreamCategory.PUBLIC


def test_kline_and_markprice_are_market_category():
    cat = validate_single_category(["btcusdt@kline_1m", "!markPrice@arr@1s"])
    assert cat == StreamCategory.MARKET


def test_mixed_categories_rejected():
    with pytest.raises(WebSocketCategoryMixError):
        validate_single_category(["btcusdt@bookTicker", "btcusdt@kline_1m"])


def test_connection_rejects_declared_category_mismatch():
    with pytest.raises(WebSocketCategoryMixError):
        BinanceWSConnection(
            ws_base="wss://fstream.binance.com",
            category=StreamCategory.MARKET,
            streams=["btcusdt@bookTicker"],
            on_message=lambda m: None,
        )


def test_connection_builds_category_scoped_url():
    conn = BinanceWSConnection(
        ws_base="wss://fstream.binance.com",
        category=StreamCategory.PUBLIC,
        streams=["btcusdt@bookTicker", "ethusdt@bookTicker"],
        on_message=lambda m: None,
    )
    url = conn._url()
    assert url.startswith("wss://fstream.binance.com/public/stream?streams=")
    assert "btcusdt@bookTicker" in url
