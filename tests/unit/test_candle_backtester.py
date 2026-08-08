from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from scalping.backtest.candle_backtester import SANITY_ONLY_BANNER, run_candle_backtest
from scalping.config.settings import EffectiveConfig
from scalping.domain.models import Candle, Side


def _make_uptrend_candles(n: int = 1500) -> tuple[list[Candle], list[Candle]]:
    """A noisy random walk with mild upward drift — enough ATR/wick variation for
    CAEMS strength to land inside the deadband/cap window periodically, unlike a
    perfectly straight ramp (which either never clears the deadband or blows past
    the strength cap depending on slope, and never lands in between). The 5m
    EMA50 alone needs 250 completed 1m bars of warmup, so `n` must comfortably
    exceed that before any evaluation is even possible.
    """
    rnd = random.Random(7)
    t0 = datetime(2026, 8, 9, 0, 0, tzinfo=UTC)
    candles_1m = []
    price = 100.0
    for i in range(n):
        open_ = price
        drift = 0.006
        noise = rnd.uniform(-0.1, 0.1)
        close = open_ + drift + noise
        wick_up = abs(rnd.uniform(0, 0.06))
        wick_down = abs(rnd.uniform(0, 0.06))
        high = max(open_, close) + wick_up
        low = min(open_, close) - wick_down
        candles_1m.append(
            Candle(
                symbol="BTCUSDT", timeframe="1m",
                open_time=t0 + timedelta(minutes=i), close_time=t0 + timedelta(minutes=i + 1),
                open=open_, high=high, low=low, close=close, quote_volume=rnd.uniform(1500, 2500),
            )
        )
        price = close

    candles_5m = []
    for i in range(0, n, 5):
        chunk = candles_1m[i : i + 5]
        if not chunk:
            continue
        candles_5m.append(
            Candle(
                symbol="BTCUSDT", timeframe="5m",
                open_time=chunk[0].open_time, close_time=chunk[-1].close_time,
                open=chunk[0].open, high=max(c.high for c in chunk), low=min(c.low for c in chunk),
                close=chunk[-1].close, quote_volume=sum(c.quote_volume for c in chunk),
            )
        )
    return candles_1m, candles_5m


def test_backtest_result_always_sanity_only():
    candles_1m, candles_5m = _make_uptrend_candles(50)
    result = run_candle_backtest(candles_1m, candles_5m, EffectiveConfig())
    assert result.sanity_only is True
    assert result.banner == SANITY_ONLY_BANNER


def test_backtest_produces_trades_on_clean_uptrend():
    candles_1m, candles_5m = _make_uptrend_candles(1500)
    result = run_candle_backtest(candles_1m, candles_5m, EffectiveConfig(), sides=(Side.LONG,))
    assert result.n > 0
    assert result.win_rate is not None


def test_backtest_metrics_consistent_with_trade_list():
    candles_1m, candles_5m = _make_uptrend_candles(1500)
    result = run_candle_backtest(candles_1m, candles_5m, EffectiveConfig(), sides=(Side.LONG,))
    if result.n > 0:
        wins = sum(1 for t in result.trades if t.r_multiple > 0)
        assert result.win_rate == wins / result.n
        expected_expectancy = sum(t.r_multiple for t in result.trades) / result.n
        assert abs(result.net_expectancy_r - expected_expectancy) < 1e-9


def test_backtest_records_rejection_counts():
    candles_1m, candles_5m = _make_uptrend_candles(1500)
    result = run_candle_backtest(candles_1m, candles_5m, EffectiveConfig(), sides=(Side.SHORT,))
    # a clean uptrend should reject shorts on regime/momentum overwhelmingly
    assert sum(result.rejection_counts.values()) > 0


def test_backtest_no_open_trade_left_dangling_within_data():
    candles_1m, candles_5m = _make_uptrend_candles(1500)
    result = run_candle_backtest(candles_1m, candles_5m, EffectiveConfig(), sides=(Side.LONG,))
    for t in result.trades:
        assert t.exit_reason in ("STOP", "TAKE_PROFIT", "TIME_STOP")
