from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from scalping.config.settings import EffectiveConfig
from scalping.domain.models import Candle, Side
from scalping.replay.replay_engine import assert_prefix_consistent, run_replay


def _make_candles(n: int, seed: int = 11) -> tuple[list[Candle], list[Candle]]:
    rnd = random.Random(seed)
    t0 = datetime(2026, 8, 9, 0, 0, tzinfo=UTC)
    candles_1m = []
    price = 100.0
    for i in range(n):
        open_ = price
        close = open_ + 0.006 + rnd.uniform(-0.1, 0.1)
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


def test_replay_deterministic_across_runs():
    candles_1m, candles_5m = _make_candles(1500)
    config = EffectiveConfig()
    r1 = run_replay(candles_1m, candles_5m, config, sides=(Side.LONG,))
    r2 = run_replay(candles_1m, candles_5m, config, sides=(Side.LONG,))
    assert r1.trades == r2.trades
    assert r1.rejection_counts == r2.rejection_counts


def test_no_lookahead_prefix_consistency():
    """A trade fully closed within the first `cutoff` bars of the full dataset
    must be identical to the same trade produced by replaying only those first
    `cutoff` bars — proving the full run's later data never reached back and
    changed an already-settled decision."""
    candles_1m, candles_5m = _make_candles(1500)
    config = EffectiveConfig()
    cutoff_idx = 1000
    cutoff_time = candles_1m[cutoff_idx].close_time

    full = run_replay(candles_1m, candles_5m, config, sides=(Side.LONG,))

    prefix_1m = candles_1m[:cutoff_idx]
    prefix_5m = [c for c in candles_5m if c.close_time <= cutoff_time]
    prefix = run_replay(prefix_1m, prefix_5m, config, sides=(Side.LONG,))

    assert_prefix_consistent(full, prefix, cutoff_time)


def test_no_lookahead_violation_is_detectable():
    """Sanity-check the assertion helper itself: feeding it two runs that
    disagree on an already-closed trade must raise."""
    from scalping.backtest.candle_backtester import BacktestResult, BacktestTrade
    from scalping.replay.replay_engine import LookaheadViolation

    t0 = datetime(2026, 8, 9, 0, 0, tzinfo=UTC)
    t1 = t0 + timedelta(minutes=5)
    full = BacktestResult(
        trades=[BacktestTrade(Side.LONG, t0, t1, 100.0, 101.0, 1.0, "TAKE_PROFIT")]
    )
    prefix = BacktestResult(
        trades=[BacktestTrade(Side.LONG, t0, t1, 100.0, 99.0, -1.0, "STOP")]  # disagrees
    )
    try:
        assert_prefix_consistent(full, prefix, t1)
        raised = False
    except LookaheadViolation:
        raised = True
    assert raised
