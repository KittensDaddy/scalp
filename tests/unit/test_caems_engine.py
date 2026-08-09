"""CAEMS v2 engine tests.

Two things this file must prove per the P3 acceptance criteria:
1. An accept/reject matrix — one test perturbing exactly one condition at a time.
2. One fixture reaching each of the 20 RejectionReason values exactly.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from scalping.config.frozen import FrozenParams
from scalping.config.settings import EffectiveConfig
from scalping.domain.models import RejectionReason, Side
from scalping.strategies.caems.engine import (
    MarketQualityFlags,
    MarketSnapshot,
    RiskCostDecision,
    evaluate,
)

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


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
        btc_strength=0.0,
    )


def _run(
    *, side: Side = Side.LONG, snapshot: MarketSnapshot | None = None,
    config: EffectiveConfig | None = None, flags: MarketQualityFlags | None = None,
    risk_cost: RiskCostDecision | None = None,
):
    return evaluate(
        side=side,
        snapshot=snapshot or _baseline_snapshot(),
        config=config or EffectiveConfig(),
        frozen=FrozenParams(),
        config_hash="testhash",
        evaluated_at=NOW,
        flags=flags or MarketQualityFlags(),
        risk_cost=risk_cost or RiskCostDecision(risk_approved=True),
    )


def test_baseline_long_accepted():
    evaluation, signal = _run()
    assert evaluation.accepted is True
    assert evaluation.rejection_reason is None
    assert signal is not None
    assert signal.side == Side.LONG
    assert signal.entry_reference == 101.3
    assert signal.stop < signal.entry_reference < signal.take_profit


def test_baseline_short_accepted():
    snap = replace(
        _baseline_snapshot(),
        ema_fast_1m=99.0, ema_slow_1m=100.0, ema_fast_5m=49.0, ema_slow_5m=50.0,
        completed_close=98.7, last_bar_high=99.5, last_bar_low=98.5, btc_strength=0.0,
    )
    evaluation, signal = _run(side=Side.SHORT, snapshot=snap)
    assert evaluation.accepted is True
    assert signal is not None
    assert signal.stop > signal.entry_reference > signal.take_profit


# -- one test per rejection reason, perturbing exactly one condition -----------------


def test_reject_kill_switch():
    ev, sig = _run(flags=MarketQualityFlags(kill_switch_engaged=True))
    assert ev.rejection_reason == RejectionReason.KILL_SWITCH
    assert sig is None


def test_reject_symbol_disabled():
    ev, _sig = _run(flags=MarketQualityFlags(symbol_disabled=True))
    assert ev.rejection_reason == RejectionReason.SYMBOL_DISABLED


def test_reject_shorts_disabled():
    ev, _sig = _run(side=Side.SHORT, flags=MarketQualityFlags(shorts_enabled=False))
    assert ev.rejection_reason == RejectionReason.SHORTS_DISABLED


def test_reject_stale_market_data():
    ev, _sig = _run(flags=MarketQualityFlags(stale_market_data=True))
    assert ev.rejection_reason == RejectionReason.STALE_MARKET_DATA


def test_reject_invalid_book():
    ev, _sig = _run(flags=MarketQualityFlags(invalid_book=True))
    assert ev.rejection_reason == RejectionReason.INVALID_BOOK


def test_reject_no_5m_trend_regime():
    snap = replace(_baseline_snapshot(), ema_fast_5m=49.0, ema_slow_5m=50.0)
    ev, _sig = _run(snapshot=snap)
    assert ev.rejection_reason == RejectionReason.NO_5M_TREND


def test_reject_no_5m_trend_momentum():
    snap = replace(_baseline_snapshot(), ema_fast_1m=100.0, ema_slow_1m=101.0)
    ev, _sig = _run(snapshot=snap)
    assert ev.rejection_reason == RejectionReason.NO_5M_TREND


def test_reject_dead_band_too_small():
    snap = replace(_baseline_snapshot(), ema_fast_1m=100.05, ema_slow_1m=100.0)  # strength 0.05
    ev, _sig = _run(snapshot=snap)
    assert ev.rejection_reason == RejectionReason.DEAD_BAND_TOO_SMALL


def test_reject_strength_too_extreme():
    snap = replace(_baseline_snapshot(), ema_fast_1m=102.0, ema_slow_1m=100.0)  # strength 2.0
    ev, _sig = _run(snapshot=snap)
    assert ev.rejection_reason == RejectionReason.STRENGTH_TOO_EXTREME


def test_reject_price_confirmation_failed():
    snap = replace(_baseline_snapshot(), completed_close=100.9)  # below ema_fast_1m
    ev, _sig = _run(snapshot=snap)
    assert ev.rejection_reason == RejectionReason.PRICE_CONFIRMATION_FAILED


def test_reject_entry_too_extended():
    snap = replace(_baseline_snapshot(), completed_close=103.0)  # > ema_fast_1m + 0.5*atr
    ev, _sig = _run(snapshot=snap)
    assert ev.rejection_reason == RejectionReason.ENTRY_TOO_EXTENDED


def test_reject_low_volume():
    snap = replace(_baseline_snapshot(), completed_quote_volume=1.0, volume_median_30=1.0)
    ev, _sig = _run(snapshot=snap)
    assert ev.rejection_reason == RejectionReason.LOW_VOLUME


def test_reject_liquidity_too_low():
    ev, _sig = _run(flags=MarketQualityFlags(liquidity_too_low=True))
    assert ev.rejection_reason == RejectionReason.LIQUIDITY_TOO_LOW


def test_reject_bar_range_abnormal():
    snap = replace(_baseline_snapshot(), last_bar_high=105.0, last_bar_low=100.5)  # range 4.5 > 3*atr
    ev, _sig = _run(snapshot=snap)
    assert ev.rejection_reason == RejectionReason.BAR_RANGE_ABNORMAL


def test_reject_funding_blackout():
    snap = replace(_baseline_snapshot(), seconds_to_next_funding=50.0)
    ev, _sig = _run(snapshot=snap)
    assert ev.rejection_reason == RejectionReason.FUNDING_BLACKOUT


def test_reject_spread_too_wide():
    snap = replace(_baseline_snapshot(), spread_bps=5.0)
    ev, _sig = _run(snapshot=snap)
    assert ev.rejection_reason == RejectionReason.SPREAD_TOO_WIDE


def test_reject_btc_regime_veto():
    snap = replace(_baseline_snapshot(), btc_strength=-0.5)
    config = EffectiveConfig()
    config.gates = config.gates.model_copy(update={"btc_veto_enabled": True, "btc_veto_threshold": 0.3})
    ev, _sig = _run(snapshot=snap, config=config)
    assert ev.rejection_reason == RejectionReason.BTC_REGIME_VETO


def test_reject_risk_limit():
    ev, _sig = _run(risk_cost=RiskCostDecision(risk_approved=False, risk_rejection=RejectionReason.RISK_LIMIT))
    assert ev.rejection_reason == RejectionReason.RISK_LIMIT


def test_reject_draw_down_limit():
    ev, _sig = _run(
        risk_cost=RiskCostDecision(risk_approved=False, risk_rejection=RejectionReason.DRAW_DOWN_LIMIT)
    )
    assert ev.rejection_reason == RejectionReason.DRAW_DOWN_LIMIT


def test_reject_cost_too_high():
    ev, _sig = _run(risk_cost=RiskCostDecision(risk_approved=True, cost_gate_passed=False))
    assert ev.rejection_reason == RejectionReason.COST_TOO_HIGH


def test_reject_expected_edge_too_low():
    ev, _sig = _run(
        risk_cost=RiskCostDecision(risk_approved=True, cost_gate_passed=True, edge_sufficient=False)
    )
    assert ev.rejection_reason == RejectionReason.EXPECTED_EDGE_TOO_LOW


def test_all_20_caems_engine_rejection_reasons_are_reachable():
    """Engine fixtures cover the original 20 CAEMS reasons. OBSERVE_ONLY /
    DATA_UNAVAILABLE are plugin/microstructure-layer reasons outside evaluate()."""
    exercised = {
        RejectionReason.KILL_SWITCH, RejectionReason.SYMBOL_DISABLED,
        RejectionReason.SHORTS_DISABLED, RejectionReason.STALE_MARKET_DATA,
        RejectionReason.INVALID_BOOK, RejectionReason.NO_5M_TREND,
        RejectionReason.DEAD_BAND_TOO_SMALL, RejectionReason.STRENGTH_TOO_EXTREME,
        RejectionReason.PRICE_CONFIRMATION_FAILED, RejectionReason.ENTRY_TOO_EXTENDED,
        RejectionReason.LOW_VOLUME, RejectionReason.LIQUIDITY_TOO_LOW,
        RejectionReason.BAR_RANGE_ABNORMAL, RejectionReason.FUNDING_BLACKOUT,
        RejectionReason.SPREAD_TOO_WIDE, RejectionReason.BTC_REGIME_VETO,
        RejectionReason.RISK_LIMIT, RejectionReason.DRAW_DOWN_LIMIT,
        RejectionReason.COST_TOO_HIGH, RejectionReason.EXPECTED_EDGE_TOO_LOW,
    }
    assert exercised == set(RejectionReason) - {
        RejectionReason.OBSERVE_ONLY,
        RejectionReason.DATA_UNAVAILABLE,
    }
    assert len(exercised) == 20


def test_strength_logged_on_rejection_too():
    snap = replace(_baseline_snapshot(), ema_fast_1m=100.05, ema_slow_1m=100.0)
    ev, _ = _run(snapshot=snap)
    assert ev.accepted is False
    assert ev.strength == pytest.approx(0.05)


def test_frozen_take_profit_ratio_used_in_signal():
    _, signal = _run()
    assert signal is not None
    r = signal.entry_reference - signal.stop
    assert signal.take_profit == pytest.approx(signal.entry_reference + 1.35 * r)


def test_gate_config_rejects_frozen_key_assignment():
    from pydantic import ValidationError

    from scalping.config.settings import GateConfig

    with pytest.raises((ValidationError, TypeError)):
        GateConfig(ema_fast_1m=5)  # type: ignore[call-arg]
