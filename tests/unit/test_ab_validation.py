from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from scalping.backtest.ab_validation import (
    build_variant_configs,
    decide_ship,
    flagged_safety_rails,
    run_ab_validation,
)
from scalping.domain.models import Candle, Side


def _make_candles(n: int, seed: int = 5) -> tuple[list[Candle], list[Candle]]:
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


def test_build_variant_configs_differ_from_each_other():
    variants = build_variant_configs()
    assert set(variants) == {"A", "B", "C", "D"}
    assert variants["A"].gates.entry_max_atr == 0.5
    assert variants["A"].exits.be_enabled is False
    assert variants["B"].exits.be_enabled is True
    assert variants["B"].gates.entry_max_atr == 999.0  # v1 baseline, not A's value
    assert variants["C"].gates.rvol_min == 1.3
    assert variants["D"].gates.entry_max_atr == 0.5
    assert variants["D"].exits.be_enabled is True
    assert variants["D"].gates.rvol_min == 1.3


def test_run_ab_validation_produces_all_four_variants():
    candles_1m, candles_5m = _make_candles(1500)
    results = run_ab_validation(candles_1m, candles_5m)
    assert set(results) == {"A", "B", "C", "D"}
    for result in results.values():
        assert result.sanity_only is True


def test_decide_ship_picks_best_single_and_compares_d():
    from scalping.backtest.candle_backtester import BacktestResult, BacktestTrade

    t0 = datetime(2026, 8, 9, 0, 0, tzinfo=UTC)
    t1 = t0 + timedelta(minutes=5)

    def trades(rs: list[float]) -> BacktestResult:
        return BacktestResult(
            trades=[
                BacktestTrade(Side.LONG, t0, t1, 100.0, 100.0 + r, r, "TAKE_PROFIT") for r in rs
            ]
        )

    results = {
        "A": trades([0.5, 0.5, -0.2]),
        "B": trades([0.1, 0.1, 0.1]),
        "C": trades([-0.5, -0.5, 0.1]),
        "D": trades([0.6, 0.6, -0.1]),  # beats best single (A) on expectancy, similar dd
    }
    decision = decide_ship(results)
    assert decision.best_single_variant == "A"
    assert decision.ship_d is True


def test_decide_ship_rejects_when_d_worse_than_best_single():
    from scalping.backtest.candle_backtester import BacktestResult, BacktestTrade

    t0 = datetime(2026, 8, 9, 0, 0, tzinfo=UTC)
    t1 = t0 + timedelta(minutes=5)

    def trades(rs: list[float]) -> BacktestResult:
        return BacktestResult(
            trades=[
                BacktestTrade(Side.LONG, t0, t1, 100.0, 100.0 + r, r, "TAKE_PROFIT") for r in rs
            ]
        )

    results = {
        "A": trades([1.0, 1.0, 1.0]),
        "B": trades([0.1]),
        "C": trades([0.1]),
        "D": trades([0.1, 0.1]),  # much worse than A
    }
    decision = decide_ship(results)
    assert decision.best_single_variant == "A"
    assert decision.ship_d is False


def test_flagged_safety_rails_empty_when_no_rejections():
    from scalping.backtest.candle_backtester import BacktestResult

    result = BacktestResult(trades=[], rejection_counts={})
    assert flagged_safety_rails(result) == {}


def test_flagged_safety_rails_flags_over_threshold():
    from scalping.backtest.candle_backtester import BacktestResult

    result = BacktestResult(
        trades=[], rejection_counts={"STRENGTH_TOO_EXTREME": 30, "LOW_VOLUME": 70}
    )
    # total = 100 evaluations (n=0 trades); STRENGTH_TOO_EXTREME rate = 0.30 > 0.2
    flagged = flagged_safety_rails(result, threshold=0.2)
    assert "STRENGTH_TOO_EXTREME" in flagged
    assert "LOW_VOLUME" not in flagged  # not a safety-rail reason at all
