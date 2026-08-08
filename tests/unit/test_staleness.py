from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scalping.market_data.staleness import Feed, StalenessWatchdog


def test_no_data_is_stale():
    wd = StalenessWatchdog()
    now = datetime.now(UTC)
    assert wd.is_stale("BTCUSDT", Feed.BOOK_TICKER, now) is True
    assert wd.data_age_ms("BTCUSDT", Feed.BOOK_TICKER, now) is None


def test_fresh_data_not_stale():
    wd = StalenessWatchdog({Feed.BOOK_TICKER: 5000})
    t0 = datetime.now(UTC)
    wd.record("BTCUSDT", Feed.BOOK_TICKER, t0)
    assert wd.is_stale("BTCUSDT", Feed.BOOK_TICKER, t0 + timedelta(seconds=1)) is False


def test_data_becomes_stale_after_threshold():
    wd = StalenessWatchdog({Feed.BOOK_TICKER: 5000})
    t0 = datetime.now(UTC)
    wd.record("BTCUSDT", Feed.BOOK_TICKER, t0)
    assert wd.is_stale("BTCUSDT", Feed.BOOK_TICKER, t0 + timedelta(seconds=6)) is True


def test_any_stale_true_if_one_feed_stale():
    wd = StalenessWatchdog({Feed.BOOK_TICKER: 5000, Feed.KLINE_1M: 90000})
    t0 = datetime.now(UTC)
    wd.record("BTCUSDT", Feed.BOOK_TICKER, t0)
    wd.record("BTCUSDT", Feed.KLINE_1M, t0)
    later = t0 + timedelta(seconds=10)
    assert wd.any_stale("BTCUSDT", later, feeds=[Feed.BOOK_TICKER, Feed.KLINE_1M]) is True


def test_data_age_ms_increases_monotonically():
    wd = StalenessWatchdog({Feed.BOOK_TICKER: 5000})
    t0 = datetime.now(UTC)
    wd.record("BTCUSDT", Feed.BOOK_TICKER, t0)
    age1 = wd.data_age_ms("BTCUSDT", Feed.BOOK_TICKER, t0 + timedelta(seconds=1))
    age2 = wd.data_age_ms("BTCUSDT", Feed.BOOK_TICKER, t0 + timedelta(seconds=2))
    assert age2 > age1
