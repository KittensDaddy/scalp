from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scalping.domain.models import Candle
from scalping.market_data.klines import ContiguityTracker, find_gaps


def _t(minute_offset: int) -> datetime:
    return datetime(2026, 8, 9, 0, 0, tzinfo=UTC) + timedelta(minutes=minute_offset)


def test_find_gaps_none_when_contiguous():
    times = [_t(i) for i in range(5)]
    assert find_gaps(times, timedelta(minutes=1)) == []


def test_find_gaps_detects_single_gap():
    times = [_t(0), _t(1), _t(5)]  # missing 2,3,4
    gaps = find_gaps(times, timedelta(minutes=1))
    assert gaps == [(_t(1), _t(5))]


def test_contiguity_tracker_no_gap_on_first_observation():
    tracker = ContiguityTracker(expected_interval=timedelta(minutes=1))
    assert tracker.observe("BTCUSDT", _t(0)) is None


def test_contiguity_tracker_detects_gap():
    tracker = ContiguityTracker(expected_interval=timedelta(minutes=1))
    tracker.observe("BTCUSDT", _t(0))
    gap = tracker.observe("BTCUSDT", _t(5))
    assert gap is not None
    assert gap.symbol == "BTCUSDT"
    assert gap.after == _t(0)
    assert gap.before == _t(5)


def test_contiguity_tracker_no_gap_for_consecutive_bars():
    tracker = ContiguityTracker(expected_interval=timedelta(minutes=1))
    tracker.observe("BTCUSDT", _t(0))
    assert tracker.observe("BTCUSDT", _t(1)) is None


def test_contiguity_tracker_ignores_duplicate_or_out_of_order():
    tracker = ContiguityTracker(expected_interval=timedelta(minutes=1))
    tracker.observe("BTCUSDT", _t(5))
    assert tracker.observe("BTCUSDT", _t(3)) is None  # out of order, not a gap
    assert tracker.observe("BTCUSDT", _t(5)) is None  # duplicate


async def test_backfill_invokes_fetcher_and_returns_candles():
    tracker = ContiguityTracker(expected_interval=timedelta(minutes=1))
    tracker.observe("BTCUSDT", _t(0))
    gap = tracker.observe("BTCUSDT", _t(5))
    assert gap is not None

    fetched_args = {}

    async def fetcher(symbol, after, before):
        fetched_args["symbol"] = symbol
        fetched_args["after"] = after
        fetched_args["before"] = before
        return [
            Candle(
                symbol=symbol, timeframe="1m", open_time=_t(i), close_time=_t(i + 1),
                open=1, high=1, low=1, close=1, quote_volume=1,
            )
            for i in range(1, 5)
        ]

    candles = await tracker.backfill(gap, fetcher)
    assert len(candles) == 4
    assert fetched_args["symbol"] == "BTCUSDT"
    assert fetched_args["after"] == _t(0)
    assert fetched_args["before"] == _t(5)
