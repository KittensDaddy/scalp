"""Candle parse + range loader."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from scalping.market_data.candles import load_backtest_candles, parse_kline_row

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def test_parse_kline_row():
    open_ms = int(NOW.timestamp() * 1000)
    close_ms = open_ms + 60_000
    c = parse_kline_row(
        "BTCUSDT",
        "1m",
        [open_ms, "100", "101", "99", "100.5", "1", close_ms, "1000000"],
    )
    assert c.symbol == "BTCUSDT"
    assert c.close == 100.5
    assert c.quote_volume == 1_000_000.0


@pytest.mark.asyncio
async def test_load_backtest_candles_aggregates_5m():
    class Fake:
        async def klines(self, symbol, interval, *, start_ms=None, end_ms=None, limit=500, budget=None):
            rows = []
            t0 = NOW
            for i in range(10):
                ts = t0 + timedelta(minutes=i)
                open_ms = int(ts.timestamp() * 1000)
                rows.append(
                    [
                        open_ms,
                        "100",
                        "101",
                        "99",
                        "100.5",
                        "1",
                        open_ms + 60_000,
                        "1000",
                    ]
                )
            return rows

    c1, c5 = await load_backtest_candles(
        Fake(), symbols=["BTCUSDT"], date_from=NOW, date_to=NOW + timedelta(minutes=10)
    )
    assert len(c1) == 10
    assert len(c5) == 2  # 10 / 5
