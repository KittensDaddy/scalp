from __future__ import annotations

import pytest

from scalping.domain.models import Side
from scalping.edge.expectancy import ExpectancyStore


def test_bucket_stats():
    store = ExpectancyStore()
    store.add_trade("BTCUSDT", Side.LONG, "trend_up", 1.35)
    store.add_trade("BTCUSDT", Side.LONG, "trend_up", -1.0)
    bucket = store.get("BTCUSDT", Side.LONG, "trend_up")
    assert bucket is not None
    assert bucket.n == 2
    assert bucket.wins == 1
    assert bucket.win_rate == pytest.approx(0.5)
    assert bucket.avg_r == pytest.approx(0.175)
    assert bucket.profit_factor == pytest.approx(1.35)


def test_missing_bucket_returns_none():
    store = ExpectancyStore()
    assert store.get("ETHUSDT", Side.SHORT, "chop") is None


def test_pooled_combines_across_symbols_same_side_regime():
    store = ExpectancyStore()
    store.add_trade("BTCUSDT", Side.LONG, "trend_up", 1.0)
    store.add_trade("ETHUSDT", Side.LONG, "trend_up", 2.0)
    store.add_trade("ETHUSDT", Side.SHORT, "trend_up", -1.0)  # different side, excluded
    pooled = store.pooled(Side.LONG, "trend_up")
    assert pooled.n == 2
    assert pooled.sum_r == pytest.approx(3.0)


def test_keys_are_coarse_side_regime_not_finer():
    """Documents the PLAN §6 constraint: bucketing is (symbol, side, regime) at
    storage granularity but callers are expected to key lookups by (side, regime)
    only via `pooled()` until sample size permits finer cuts."""
    store = ExpectancyStore()
    store.add_trade("BTCUSDT", Side.LONG, "trend_up", 1.0)
    assert store.get("BTCUSDT", Side.LONG, "trend_up") is not None
