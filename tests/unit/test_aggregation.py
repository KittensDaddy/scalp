from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scalping.domain.models import Candle
from scalping.market_data.aggregation import StreamingAggregator, aggregate_candles


def _candle(i: int, close: float) -> Candle:
    t0 = datetime(2026, 8, 9, 0, 0, tzinfo=UTC)
    return Candle(
        symbol="BTCUSDT", timeframe="1m",
        open_time=t0 + timedelta(minutes=i), close_time=t0 + timedelta(minutes=i + 1),
        open=close - 0.5, high=close + 0.5, low=close - 1.0, close=close, quote_volume=100.0,
    )


def test_aggregate_5m_from_15_1m_candles():
    candles = [_candle(i, 100.0 + i) for i in range(15)]
    out = aggregate_candles(candles, "5m")
    assert len(out) == 3
    first = out[0]
    assert first.timeframe == "5m"
    assert first.open == candles[0].open
    assert first.close == candles[4].close
    assert first.high == max(c.high for c in candles[:5])
    assert first.low == min(c.low for c in candles[:5])
    assert first.quote_volume == sum(c.quote_volume for c in candles[:5])
    assert first.open_time == candles[0].open_time
    assert first.close_time == candles[4].close_time


def test_incomplete_trailing_bucket_dropped():
    candles = [_candle(i, 100.0 + i) for i in range(7)]  # 1 full 5m bucket + 2 leftover
    out = aggregate_candles(candles, "5m")
    assert len(out) == 1


def test_3m_and_15m_factors():
    candles = [_candle(i, 100.0 + i) for i in range(30)]
    assert len(aggregate_candles(candles, "3m")) == 10
    assert len(aggregate_candles(candles, "15m")) == 2


def test_streaming_aggregator_emits_only_on_bucket_close():
    agg = StreamingAggregator("5m")
    results = [agg.on_1m_candle(_candle(i, 100.0 + i)) for i in range(5)]
    assert results[:4] == [None, None, None, None]
    assert results[4] is not None
    assert results[4].timeframe == "5m"


def test_streaming_aggregator_matches_batch_aggregation():
    candles = [_candle(i, 100.0 + i) for i in range(20)]
    batch = aggregate_candles(candles, "5m")
    agg = StreamingAggregator("5m")
    streaming = [r for c in candles if (r := agg.on_1m_candle(c)) is not None]
    assert streaming == batch
