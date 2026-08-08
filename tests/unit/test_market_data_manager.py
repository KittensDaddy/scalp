from __future__ import annotations

from datetime import UTC, datetime

from scalping.config.frozen import FrozenParams
from scalping.market_data.manager import MarketDataManager
from scalping.market_data.registry import SymbolStateRegistry

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def _manager() -> MarketDataManager:
    return MarketDataManager(
        ws_base="wss://fstream.binance.com", registry=SymbolStateRegistry(FrozenParams())
    )


def test_handle_book_ticker_message_updates_registry():
    mgr = _manager()
    msg = {"s": "BTCUSDT", "b": "99.9", "B": "1", "a": "100.1", "A": "1"}
    bt = mgr.handle_book_ticker_message(msg, received_at=NOW)
    assert bt.symbol == "BTCUSDT"
    assert mgr.registry.get("BTCUSDT").last_book_ticker == bt


def test_handle_book_ticker_records_latency():
    mgr = _manager()
    msg = {"s": "BTCUSDT", "b": "99.9", "B": "1", "a": "100.1", "A": "1", "E": int(NOW.timestamp() * 1000)}
    mgr.handle_book_ticker_message(msg, received_at=NOW)
    stats = mgr.latency.stats("book_ticker")
    assert stats["n"] == 1
    assert stats["p50"] >= 0


def test_handle_kline_message_ignores_unclosed_candle():
    mgr = _manager()
    msg = {
        "s": "BTCUSDT",
        "k": {"t": 0, "T": 60_000, "o": "100", "h": "101", "l": "99", "c": "100.5", "q": "1000", "x": False},
    }
    result = mgr.handle_kline_message(msg, received_at=NOW)
    assert result.candle is None
    assert mgr.registry.get("BTCUSDT") is None


def test_handle_kline_message_processes_closed_candle():
    mgr = _manager()
    msg = {
        "s": "BTCUSDT",
        "k": {"t": 0, "T": 60_000, "o": "100", "h": "101", "l": "99", "c": "100.5", "q": "1000", "x": True},
    }
    result = mgr.handle_kline_message(msg, received_at=NOW)
    assert result.candle is not None
    assert result.candle.close == 100.5
    assert result.gap is None  # first candle, nothing to compare against
    assert mgr.registry.get("BTCUSDT").last_candle_1m == result.candle


def test_handle_kline_message_detects_gap():
    mgr = _manager()

    def kline_msg(t_ms: int, close: str) -> dict:
        return {
            "s": "BTCUSDT",
            "k": {"t": t_ms, "T": t_ms + 60_000, "o": "100", "h": "101", "l": "99", "c": close,
                  "q": "1000", "x": True},
        }

    mgr.handle_kline_message(kline_msg(0, "100"), received_at=NOW)
    result = mgr.handle_kline_message(kline_msg(5 * 60_000, "101"), received_at=NOW)  # 5-bar gap
    assert result.gap is not None
    assert result.gap.symbol == "BTCUSDT"


def test_rebalance_produces_public_and_market_plans():
    mgr = _manager()
    public_plan, market_plan = mgr.rebalance({"BTCUSDT", "ETHUSDT"})
    assert public_plan.all_symbols == {"BTCUSDT", "ETHUSDT"}
    assert market_plan.all_symbols == {"BTCUSDT", "ETHUSDT"}


def test_build_streams_lowercases_and_suffixes():
    assert MarketDataManager.build_public_streams(["BTCUSDT"]) == ["btcusdt@bookTicker"]
    assert MarketDataManager.build_market_streams(["BTCUSDT"]) == ["btcusdt@kline_1m"]


def test_build_connections_uses_injected_factory_per_shard():
    calls = []

    def fake_factory(**kwargs):
        calls.append(kwargs)
        return object()

    mgr = MarketDataManager(
        ws_base="wss://fstream.binance.com", registry=SymbolStateRegistry(FrozenParams()),
        max_streams_per_shard=1, shard_factory=fake_factory,
    )
    mgr.rebalance({"BTCUSDT", "ETHUSDT"})
    connections = mgr.build_connections()

    # 2 symbols, max 1 per shard -> 2 public shards + 2 market shards
    assert len(connections) == 4
    categories = {c["category"].value for c in calls}
    assert categories == {"public", "market"}
