from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scalping.market_data.latency import LatencyTracker


def test_records_and_reports_stats():
    tracker = LatencyTracker()
    t0 = datetime(2026, 8, 9, 0, 0, tzinfo=UTC)
    for ms in [10, 20, 30, 40, 50]:
        tracker.record("book_ticker", exchange_ts=t0, local_ts=t0 + timedelta(milliseconds=ms))
    stats = tracker.stats("book_ticker")
    assert stats["n"] == 5
    assert stats["p50"] == 30
    assert stats["p99"] == 50


def test_unknown_stage_returns_empty_stats():
    tracker = LatencyTracker()
    stats = tracker.stats("nope")
    assert stats["n"] == 0
    assert stats["p50"] is None


def test_stages_lists_recorded_stage_names():
    tracker = LatencyTracker()
    t0 = datetime(2026, 8, 9, 0, 0, tzinfo=UTC)
    tracker.record("book_ticker", exchange_ts=t0, local_ts=t0)
    tracker.record("kline_1m", exchange_ts=t0, local_ts=t0)
    assert set(tracker.stages()) == {"book_ticker", "kline_1m"}


def test_window_bounds_memory():
    tracker = LatencyTracker(window=3)
    t0 = datetime(2026, 8, 9, 0, 0, tzinfo=UTC)
    for i in range(10):
        tracker.record("x", exchange_ts=t0, local_ts=t0 + timedelta(milliseconds=i))
    assert tracker.stats("x")["n"] == 3
