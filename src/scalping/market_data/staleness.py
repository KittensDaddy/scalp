"""Per-feed staleness tracking.

SCANNER_DASHBOARD_PLAN.md §D: "every SymbolState carries last_event_ts per feed; a
watchdog marks data_age_ms; any gate sees stale=True -> signal suppressed and
rejection reason recorded."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class Feed(StrEnum):
    BOOK_TICKER = "book_ticker"
    KLINE_1M = "kline_1m"
    MARK_PRICE = "mark_price"
    USER_STREAM = "user_stream"


@dataclass
class FeedFreshness:
    """Tracks last_event_ts for one feed and answers is-stale queries."""

    max_age_ms: int
    _last_event_ts: datetime | None = field(default=None, repr=False)

    def record(self, event_ts: datetime) -> None:
        if self._last_event_ts is None or event_ts >= self._last_event_ts:
            self._last_event_ts = event_ts

    def data_age_ms(self, now: datetime) -> float | None:
        if self._last_event_ts is None:
            return None
        return (now - self._last_event_ts).total_seconds() * 1000.0

    def is_stale(self, now: datetime) -> bool:
        age = self.data_age_ms(now)
        return age is None or age > self.max_age_ms


class StalenessWatchdog:
    """Owns :class:`FeedFreshness` per (symbol, feed) pair."""

    def __init__(self, max_age_ms: dict[Feed, int] | None = None) -> None:
        self._defaults = max_age_ms or {
            Feed.BOOK_TICKER: 5_000,
            Feed.KLINE_1M: 90_000,
            Feed.MARK_PRICE: 5_000,
            Feed.USER_STREAM: 60_000,
        }
        self._state: dict[tuple[str, Feed], FeedFreshness] = {}

    def _get(self, symbol: str, feed: Feed) -> FeedFreshness:
        key = (symbol, feed)
        if key not in self._state:
            self._state[key] = FeedFreshness(max_age_ms=self._defaults[feed])
        return self._state[key]

    def record(self, symbol: str, feed: Feed, event_ts: datetime) -> None:
        self._get(symbol, feed).record(event_ts)

    def is_stale(self, symbol: str, feed: Feed, now: datetime) -> bool:
        return self._get(symbol, feed).is_stale(now)

    def any_stale(self, symbol: str, now: datetime, feeds: list[Feed] | None = None) -> bool:
        feeds = feeds or list(self._defaults)
        return any(self.is_stale(symbol, f, now) for f in feeds)

    def data_age_ms(self, symbol: str, feed: Feed, now: datetime) -> float | None:
        return self._get(symbol, feed).data_age_ms(now)
