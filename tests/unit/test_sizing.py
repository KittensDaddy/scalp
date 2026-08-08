from __future__ import annotations

import pytest

from scalping.config.settings import RiskConfig
from scalping.risk.sizing import InvalidStopError, SizingInputs, compute_position_size


def _inputs(**overrides) -> SizingInputs:
    defaults = dict(
        equity=10_000.0, entry=100.0, stop=99.0, available_depth=100_000.0,
        bar_volume=100_000.0, exchange_max_notional=1_000_000.0,
    )
    defaults.update(overrides)
    return SizingInputs(**defaults)


def test_risk_notional_binds_when_smallest():
    risk = RiskConfig(risk_per_trade_pct=0.15, leverage_cap=100, depth_size_frac=1.0,
                       volume_cap_frac=1.0, exchange_cap_frac=1.0)
    result = compute_position_size(_inputs(), risk)
    stop_fraction = 1.0 / 100.0
    expected_risk_notional = 10_000.0 * 0.0015 / stop_fraction
    assert result.size == pytest.approx(expected_risk_notional)
    assert result.binding_cap == "risk_notional"


def test_depth_cap_binds_when_smallest():
    risk = RiskConfig(risk_per_trade_pct=50.0, leverage_cap=100, depth_size_frac=0.01,
                       volume_cap_frac=1.0, exchange_cap_frac=1.0)
    result = compute_position_size(_inputs(available_depth=1000.0), risk)
    assert result.binding_cap == "depth_cap"
    assert result.size == pytest.approx(10.0)


def test_leverage_cap_binds():
    risk = RiskConfig(risk_per_trade_pct=50.0, leverage_cap=1.0, depth_size_frac=1.0,
                       volume_cap_frac=1.0, exchange_cap_frac=1.0)
    result = compute_position_size(_inputs(equity=10_000.0), risk)
    assert result.binding_cap == "leverage_cap"
    assert result.size == pytest.approx(10_000.0)


def test_zero_stop_distance_raises():
    risk = RiskConfig()
    with pytest.raises(InvalidStopError):
        compute_position_size(_inputs(stop=100.0), risk)


def test_risk_per_trade_multiplier_scales_down_size():
    risk = RiskConfig(risk_per_trade_pct=0.15, risk_per_trade_multiplier=0.75,
                       leverage_cap=100, depth_size_frac=1.0, volume_cap_frac=1.0,
                       exchange_cap_frac=1.0)
    result = compute_position_size(_inputs(), risk)
    stop_fraction = 1.0 / 100.0
    expected = 10_000.0 * 0.0015 * 0.75 / stop_fraction
    assert result.size == pytest.approx(expected)
