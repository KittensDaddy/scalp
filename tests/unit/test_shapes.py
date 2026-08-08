from __future__ import annotations

import pytest

from scalping.exchanges.binance.shapes import (
    ShapeMismatch,
    check_algo_order_ack_shape,
    check_book_ticker_shape,
    check_kline_shape,
    check_user_stream_shape,
)


def test_book_ticker_shape_ok():
    check_book_ticker_shape({"s": "BTCUSDT", "b": "1", "B": "1", "a": "1", "A": "1"})


def test_book_ticker_shape_missing_field():
    with pytest.raises(ShapeMismatch, match="missing fields"):
        check_book_ticker_shape({"s": "BTCUSDT", "b": "1", "B": "1"})


def test_kline_shape_ok():
    check_kline_shape({"k": {"t": 1, "T": 2, "o": "1", "h": "1", "l": "1", "c": "1", "q": "1", "x": True}})


def test_kline_shape_missing_wrapper():
    with pytest.raises(ShapeMismatch, match="'k'"):
        check_kline_shape({"e": "kline"})


def test_kline_shape_missing_inner_field():
    with pytest.raises(ShapeMismatch):
        check_kline_shape({"k": {"t": 1, "T": 2}})


def test_user_stream_shape_ok():
    check_user_stream_shape({"e": "ORDER_TRADE_UPDATE"})


def test_user_stream_shape_missing_event_type():
    with pytest.raises(ShapeMismatch):
        check_user_stream_shape({"o": {}})


def test_algo_order_ack_shape_ok():
    check_algo_order_ack_shape({"algoId": 1, "symbol": "BTCUSDT", "algoType": "STOP_MARKET"})


def test_algo_order_ack_shape_missing_field():
    with pytest.raises(ShapeMismatch, match="algoType"):
        check_algo_order_ack_shape({"algoId": 1, "symbol": "BTCUSDT"})
