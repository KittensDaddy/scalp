"""Kline contiguity validation and gap-triggered REST backfill.

PLAN_OF_ACTION.md §2a / SCANNER_DASHBOARD_PLAN.md §D: klines are validated for
contiguous open times; gaps trigger REST backfill before the symbol becomes eligible
again. This module is transport-agnostic — `find_gaps` operates on plain timestamps so
it's testable without a real WS/REST client; the Binance adapter (P6) wires a real
`BackfillFetcher` into `ContiguityTracker.backfill`.
"""

from __future__ import annotations

import itertools
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from scalping.domain.models import Candle

BackfillFetcher = Callable[[str, datetime, datetime], Awaitable[list[Candle]]]


@dataclass
class Gap:
    symbol: str
    after: datetime
    before: datetime


def find_gaps(
    open_times: list[datetime], expected_interval: timedelta
) -> list[tuple[datetime, datetime]]:
    """Return (after, before) pairs bracketing every missing interval in a sorted
    sequence of candle open_times."""
    gaps: list[tuple[datetime, datetime]] = []
    for prev, curr in itertools.pairwise(open_times):
        delta = curr - prev
        if delta > expected_interval:
            gaps.append((prev, curr))
    return gaps


class ContiguityTracker:
    """Tracks the last-seen kline open_time per symbol and detects gaps as new
    candles arrive, one at a time (streaming use — the batch `find_gaps` above is for
    backfill result validation)."""

    def __init__(self, expected_interval: timedelta = timedelta(minutes=1)) -> None:
        self.expected_interval = expected_interval
        self._last_open_time: dict[str, datetime] = {}

    def observe(self, symbol: str, open_time: datetime) -> Gap | None:
        prev = self._last_open_time.get(symbol)
        self._last_open_time[symbol] = max(open_time, prev) if prev else open_time
        if prev is None:
            return None
        if open_time <= prev:
            return None  # duplicate/out-of-order, not a gap
        delta = open_time - prev
        if delta > self.expected_interval:
            return Gap(symbol=symbol, after=prev, before=open_time)
        return None

    async def backfill(self, gap: Gap, fetcher: BackfillFetcher) -> list[Candle]:
        return await fetcher(gap.symbol, gap.after, gap.before)
