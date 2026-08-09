"""Historical candle helpers for Lab backtests + registry warm-up."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from scalping.domain.models import Candle
from scalping.exchanges.base.rate_limiter import Budget
from scalping.market_data.aggregation import aggregate_candles


class KlineSource(Protocol):
    async def klines(
        self,
        symbol: str,
        interval: str,
        *,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 500,
        budget: Budget = Budget.MARKET,
    ) -> list[list[Any]]: ...


def parse_kline_row(symbol: str, interval: str, row: list[Any]) -> Candle:
    """Binance kline array → Candle."""
    open_ms = int(row[0])
    o, h, low, c = row[1], row[2], row[3], row[4]
    close_ms = int(row[6])
    quote_vol = row[7]
    return Candle(
        symbol=symbol,
        timeframe=interval,
        open_time=datetime.fromtimestamp(open_ms / 1000, tz=UTC),
        close_time=datetime.fromtimestamp(close_ms / 1000, tz=UTC),
        open=float(o),
        high=float(h),
        low=float(low),
        close=float(c),
        quote_volume=float(quote_vol),
        is_closed=True,
    )


async def fetch_klines_range(
    source: KlineSource,
    *,
    symbol: str,
    interval: str,
    start: datetime,
    end: datetime,
    limit: int = 1500,
) -> list[Candle]:
    """Paginate Binance klines covering [start, end]."""
    out: list[Candle] = []
    cursor_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    while cursor_ms < end_ms:
        rows = await source.klines(
            symbol,
            interval,
            start_ms=cursor_ms,
            end_ms=end_ms,
            limit=limit,
            budget=Budget.BACKFILL,
        )
        if not rows:
            break
        for row in rows:
            out.append(parse_kline_row(symbol, interval, row))
        last_open = int(rows[-1][0])
        next_cursor = last_open + 1
        if next_cursor <= cursor_ms:
            break
        cursor_ms = next_cursor
        if len(rows) < limit:
            break
    return out


async def load_backtest_candles(
    source: KlineSource,
    *,
    symbols: list[str],
    date_from: datetime,
    date_to: datetime,
) -> tuple[list[Candle], list[Candle]]:
    """Fetch 1m candles and derive 5m aggregates for the candle backtester."""
    candles_1m: list[Candle] = []
    for symbol in symbols:
        candles_1m.extend(
            await fetch_klines_range(
                source, symbol=symbol, interval="1m", start=date_from, end=date_to
            )
        )
    by_symbol: dict[str, list[Candle]] = {}
    for c in candles_1m:
        by_symbol.setdefault(c.symbol, []).append(c)
    candles_5m: list[Candle] = []
    for sym_candles in by_symbol.values():
        candles_5m.extend(aggregate_candles(sym_candles, "5m"))
    return candles_1m, candles_5m
