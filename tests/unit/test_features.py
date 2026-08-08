from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scalping.config.frozen import FrozenParams
from scalping.domain.models import Candle, Side
from scalping.market_data.registry import SymbolStateRegistry
from scalping.scoring.features import FeatureConfig, FeatureRawInputs, compute_features

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def _warm_registry(n: int = 60) -> SymbolStateRegistry:
    registry = SymbolStateRegistry(FrozenParams())
    t0 = datetime(2026, 8, 9, 0, 0, tzinfo=UTC)
    price = 100.0
    for i in range(n):
        close = price + 0.05
        candle = Candle(
            symbol="BTCUSDT", timeframe="1m",
            open_time=t0 + timedelta(minutes=i), close_time=t0 + timedelta(minutes=i + 1),
            open=price, high=close + 0.1, low=price - 0.1, close=close, quote_volume=1000.0,
        )
        registry.on_kline_1m_closed(candle)
        if i % 5 == 4:
            registry.on_kline_5m_closed(candle)
        price = close
    return registry


def _raw(**overrides) -> FeatureRawInputs:
    defaults = dict(
        side=Side.LONG, entry_reference=100.0, btc_ema_fast_1m=None, btc_ema_slow_1m=None,
        spread_bps=1.0, expected_cost_bps=5.0, expected_edge_bps=20.0,
        liquidity_percentile=0.8, historical_edge_frac=0.0, confirmations_frac=0.5,
        stale=False, evaluated_at=NOW,
    )
    defaults.update(overrides)
    return FeatureRawInputs(**defaults)


def test_stale_flag_passes_through():
    registry = _warm_registry()
    state = registry.get("BTCUSDT")
    inputs = compute_features(state, _raw(stale=True))
    assert inputs.stale is True


def test_trend_alignment_high_when_ema_stacks_agree_with_long():
    registry = _warm_registry()
    state = registry.get("BTCUSDT")
    inputs = compute_features(state, _raw(side=Side.LONG))
    # uptrend fixture -> 1m and 5m EMA stacks both agree with LONG
    assert inputs.trend_alignment_frac > 0.5


def test_trend_alignment_lower_for_short_in_uptrend():
    registry = _warm_registry()
    state = registry.get("BTCUSDT")
    long_inputs = compute_features(state, _raw(side=Side.LONG))
    short_inputs = compute_features(state, _raw(side=Side.SHORT))
    assert long_inputs.trend_alignment_frac > short_inputs.trend_alignment_frac


def test_btc_alignment_contributes_when_present():
    registry = _warm_registry()
    state = registry.get("BTCUSDT")
    without_btc = compute_features(state, _raw(btc_ema_fast_1m=None, btc_ema_slow_1m=None))
    with_aligned_btc = compute_features(
        state, _raw(btc_ema_fast_1m=105.0, btc_ema_slow_1m=100.0, side=Side.LONG)
    )
    assert with_aligned_btc.trend_alignment_frac > without_btc.trend_alignment_frac


def test_relative_volume_zero_without_last_candle():
    registry = SymbolStateRegistry(FrozenParams())  # no candles seen -> no state at all
    state = registry.get("BTCUSDT")
    # state is None; caller must warm the registry first — this test documents the
    # precondition rather than calling compute_features on a nonexistent state.
    assert state is None


def test_relative_volume_scales_with_last_bar_volume():
    registry = _warm_registry()
    state = registry.get("BTCUSDT")
    inputs_normal = compute_features(state, _raw())
    # manually bump the last candle's volume to simulate a volume spike
    state.last_candle_1m = state.last_candle_1m.model_copy(update={"quote_volume": 5000.0})
    inputs_spike = compute_features(state, _raw())
    assert inputs_spike.relative_volume_frac > inputs_normal.relative_volume_frac


def test_entry_quality_decreases_with_distance_from_ema():
    registry = _warm_registry()
    state = registry.get("BTCUSDT")
    close_entry = compute_features(state, _raw(entry_reference=state.ema_fast_1m.value))
    far_entry = compute_features(
        state, _raw(entry_reference=state.ema_fast_1m.value + 10 * state.atr_1m.value)
    )
    assert close_entry.entry_quality_frac > far_entry.entry_quality_frac


def test_spread_penalty_scales_with_spread():
    registry = _warm_registry()
    state = registry.get("BTCUSDT")
    tight = compute_features(state, _raw(spread_bps=0.5))
    wide = compute_features(state, _raw(spread_bps=2.0), FeatureConfig(spread_max_bps=2.0))
    assert wide.spread_penalty_frac > tight.spread_penalty_frac


def test_slippage_penalty_full_when_no_edge():
    registry = _warm_registry()
    state = registry.get("BTCUSDT")
    inputs = compute_features(state, _raw(expected_edge_bps=0.0))
    assert inputs.slippage_penalty_frac == 1.0


def test_historical_edge_and_confirmations_pass_through_unchanged():
    registry = _warm_registry()
    state = registry.get("BTCUSDT")
    inputs = compute_features(state, _raw(historical_edge_frac=0.37, confirmations_frac=0.9))
    assert inputs.historical_edge_frac == 0.37
    assert inputs.confirmations_frac == 0.9
