"""Incremental-vs-batch parity tests.

SCANNER_DASHBOARD_PLAN.md §L: "incremental indicators vs batch reference" is an
explicit required test. The batch reference implementations here are intentionally
naive (full recompute every step) so they're trivially correct by inspection, and the
incremental classes in `scalping.indicators.incremental` must match them to float
tolerance over random-walk fixtures.
"""

from __future__ import annotations

import random

import pytest

from scalping.indicators.incremental import ATR, EMA, RSI, RollingMedian


def batch_ema(prices: list[float], period: int) -> list[float | None]:
    out: list[float | None] = []
    alpha = 2.0 / (period + 1.0)
    value = None
    for i, p in enumerate(prices):
        if value is None:
            if i + 1 < period:
                out.append(None)
                continue
            value = sum(prices[i + 1 - period : i + 1]) / period
        else:
            value = (p - value) * alpha + value
        out.append(value)
    return out


def batch_atr(highs: list[float], lows: list[float], closes: list[float], period: int):
    trs = []
    for i in range(len(highs)):
        if i == 0:
            trs.append(highs[i] - lows[i])
        else:
            trs.append(
                max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1]),
                )
            )
    out: list[float | None] = []
    value = None
    for i, tr in enumerate(trs):
        if value is None:
            if i + 1 < period:
                out.append(None)
                continue
            value = sum(trs[i + 1 - period : i + 1]) / period
        else:
            value = (value * (period - 1) + tr) / period
        out.append(value)
    return out


def batch_median(values: list[float], window: int) -> list[float | None]:
    out: list[float | None] = []
    for i in range(len(values)):
        window_vals = values[max(0, i - window + 1) : i + 1]
        if len(window_vals) < 1:
            out.append(None)
            continue
        s = sorted(window_vals)
        n = len(s)
        mid = n // 2
        out.append(s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2)
    return out


@pytest.fixture
def random_walk():
    rnd = random.Random(42)
    prices = [100.0]
    for _ in range(199):
        prices.append(prices[-1] + rnd.uniform(-1, 1))
    highs = [p + abs(rnd.uniform(0, 0.5)) for p in prices]
    lows = [p - abs(rnd.uniform(0, 0.5)) for p in prices]
    return prices, highs, lows


def test_ema_matches_batch_reference(random_walk):
    prices, _, _ = random_walk
    period = 12
    expected = batch_ema(prices, period)
    ema = EMA(period)
    actual = [ema.update(p) for p in prices]
    for e, a in zip(expected, actual, strict=True):
        if e is None:
            assert a is None
        else:
            assert a == pytest.approx(e, rel=1e-9)


def test_ema_48_matches_batch_reference(random_walk):
    prices, _, _ = random_walk
    period = 48
    expected = batch_ema(prices, period)
    ema = EMA(period)
    actual = [ema.update(p) for p in prices]
    for e, a in zip(expected, actual, strict=True):
        if e is None:
            assert a is None
        else:
            assert a == pytest.approx(e, rel=1e-9)


def test_atr_matches_batch_reference(random_walk):
    prices, highs, lows = random_walk
    period = 14
    expected = batch_atr(highs, lows, prices, period)
    atr = ATR(period)
    actual = [atr.update(h, low, c) for h, low, c in zip(highs, lows, prices, strict=True)]
    for e, a in zip(expected, actual, strict=True):
        if e is None:
            assert a is None
        else:
            assert a == pytest.approx(e, rel=1e-9)


def test_rolling_median_matches_batch_reference(random_walk):
    prices, _, _ = random_walk
    window = 30
    expected = batch_median(prices, window)
    rm = RollingMedian(window)
    actual = []
    for p in prices:
        actual.append(rm.median())
        rm.update(p)
    # actual[i] is the median *before* seeing prices[i]; shift expected by one to
    # match "prior N completed bars" semantics (strategy-caems.md: current bar excluded)
    shifted_expected = [None, *expected[:-1]]
    for e, a in zip(shifted_expected, actual, strict=True):
        if e is None:
            assert a is None
        else:
            assert a == pytest.approx(e, rel=1e-9)


def test_ema_not_ready_before_period():
    ema = EMA(5)
    for _ in range(4):
        assert ema.update(100.0) is None
    assert ema.update(100.0) is not None


def test_rsi_bounded_0_100(random_walk):
    prices, _, _ = random_walk
    rsi = RSI(14)
    for p in prices:
        v = rsi.update(p)
        if v is not None:
            assert 0.0 <= v <= 100.0


def test_rsi_all_gains_is_100():
    rsi = RSI(3)
    prices = [100, 101, 102, 103, 104, 105]
    values = [rsi.update(p) for p in prices]
    assert values[-1] == pytest.approx(100.0)
