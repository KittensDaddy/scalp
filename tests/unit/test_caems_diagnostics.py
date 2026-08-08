"""CAEMS diagnostics tests — S7 condition-diff correctness fixtures."""

from __future__ import annotations

from dataclasses import replace

from scalping.config.frozen import FrozenParams
from scalping.config.settings import EffectiveConfig
from scalping.domain.models import Side
from scalping.strategies.caems.diagnostics import evaluate_conditions
from scalping.strategies.caems.engine import MarketSnapshot


def _baseline_snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        symbol="BTCUSDT",
        ema_fast_1m=101.0,
        ema_slow_1m=100.0,
        ema_fast_5m=51.0,
        ema_slow_5m=50.0,
        atr14_1m=1.0,
        completed_close=101.3,
        last_bar_high=101.5,
        last_bar_low=100.5,
        completed_quote_volume=2.0,
        volume_median_30=1.0,
        spread_bps=1.0,
        seconds_to_next_funding=1000.0,
    )


def _checks(snapshot, side=Side.LONG):
    return evaluate_conditions(
        side=side, snapshot=snapshot, config=EffectiveConfig(), frozen=FrozenParams(),
    )


def test_baseline_all_ten_conditions_pass():
    checks = _checks(_baseline_snapshot())
    assert len(checks) == 10
    assert all(c.passed for c in checks)


def test_evaluates_every_condition_independently_no_short_circuit():
    """Two simultaneously-broken conditions (regime + volume) must both show up as
    failing — proof this isn't a cascade like `engine.evaluate`."""
    snap = replace(
        _baseline_snapshot(), ema_fast_5m=49.0, ema_slow_5m=50.0,
        completed_quote_volume=1.0, volume_median_30=1.0,
    )
    checks = _checks(snap)
    failing = {c.name for c in checks if not c.passed}
    assert failing == {"regime_5m", "volume"}


def test_only_deadband_fails_when_strength_below_min():
    # move ema_slow closer to ema_fast (not ema_fast itself) so entry_location's
    # extension-from-ema_fast_1m calculation is unaffected.
    snap = replace(_baseline_snapshot(), ema_slow_1m=100.95)
    checks = _checks(snap)
    failing = {c.name for c in checks if not c.passed}
    assert failing == {"deadband"}


def test_short_side_mirrors_long():
    snap = replace(
        _baseline_snapshot(),
        ema_fast_1m=99.0, ema_slow_1m=100.0, ema_fast_5m=49.0, ema_slow_5m=50.0,
        completed_close=98.7, last_bar_high=99.5, last_bar_low=98.5,
    )
    checks = _checks(snap, side=Side.SHORT)
    assert all(c.passed for c in checks)


def test_detail_strings_carry_numeric_margins():
    snap = replace(_baseline_snapshot(), spread_bps=5.0)
    checks = _checks(snap)
    spread_check = next(c for c in checks if c.name == "spread")
    assert spread_check.passed is False
    assert "5.0" in spread_check.detail or "5.000" in spread_check.detail
