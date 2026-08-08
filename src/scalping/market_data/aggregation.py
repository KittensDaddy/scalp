"""1m -> 3m/5m/15m candle aggregation.

SCANNER_DASHBOARD_PLAN.md §D: "derive 3m/5m/15m by aggregation (avoids 4x stream
count)" — only `@kline_1m` is subscribed per symbol; every other timeframe is
built from it locally rather than opening additional streams.
"""

from __future__ import annotations

from typing import Literal

from scalping.domain.models import Candle

_FACTORS: dict[str, int] = {"3m": 3, "5m": 5, "15m": 15}


def aggregate_candles(
    candles_1m: list[Candle], timeframe: Literal["3m", "5m", "15m"]
) -> list[Candle]:
    """Groups consecutive completed 1m candles into buckets of the target
    timeframe's factor. A bucket is only emitted once it has exactly `factor`
    1m candles — a partial trailing bucket (incomplete timeframe candle) is
    dropped, never emitted as if it were closed.
    """
    factor = _FACTORS[timeframe]
    out: list[Candle] = []
    complete_len = len(candles_1m) - (len(candles_1m) % factor)
    for i in range(0, complete_len, factor):
        chunk = candles_1m[i : i + factor]
        out.append(
            Candle(
                symbol=chunk[0].symbol, timeframe=timeframe,
                open_time=chunk[0].open_time, close_time=chunk[-1].close_time,
                open=chunk[0].open, high=max(c.high for c in chunk),
                low=min(c.low for c in chunk), close=chunk[-1].close,
                quote_volume=sum(c.quote_volume for c in chunk),
            )
        )
    return out


class StreamingAggregator:
    """Streaming variant: feed one completed 1m candle at a time, get back a
    completed aggregate candle exactly when the bucket closes (or `None`
    otherwise). Used by the live pipeline, which sees candles one at a time
    rather than as a batch.
    """

    def __init__(self, timeframe: Literal["3m", "5m", "15m"]) -> None:
        self.timeframe = timeframe
        self._factor = _FACTORS[timeframe]
        self._buffer: list[Candle] = []

    def on_1m_candle(self, candle: Candle) -> Candle | None:
        self._buffer.append(candle)
        if len(self._buffer) < self._factor:
            return None
        chunk, self._buffer = self._buffer, []
        return Candle(
            symbol=chunk[0].symbol, timeframe=self.timeframe,
            open_time=chunk[0].open_time, close_time=chunk[-1].close_time,
            open=chunk[0].open, high=max(c.high for c in chunk),
            low=min(c.low for c in chunk), close=chunk[-1].close,
            quote_volume=sum(c.quote_volume for c in chunk),
        )
