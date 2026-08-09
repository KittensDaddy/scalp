"""Developing Setups engine tests — S7 acceptance: near-trigger detection with an
accurate missing-condition list."""

from __future__ import annotations

from datetime import UTC, datetime

from scalping.domain.models import Side
from scalping.scanner.developing import (
    DevelopingSetupsService,
    NearTriggerConfig,
    detect_developing_setup,
    detect_developing_setups,
)
from scalping.strategies.caems.diagnostics import ConditionCheck

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def _checks(*failing: str) -> list[ConditionCheck]:
    names = [
        "regime_5m", "momentum_1m", "deadband", "strength_cap", "price_confirmation",
        "entry_location", "volume", "candle_quality", "funding_blackout", "spread",
    ]
    return [ConditionCheck(n, n not in failing, f"{n} detail") for n in names]


def test_accepted_row_is_never_developing():
    setup = detect_developing_setup(
        symbol="BTCUSDT", side=Side.LONG, score=95.0, accepted=True,
        conditions=_checks(), config=NearTriggerConfig(), evaluated_at=NOW,
    )
    assert setup is None


def test_rejected_row_far_below_threshold_is_not_developing():
    cfg = NearTriggerConfig(
        score_threshold=70.0, score_delta=20.0, min_passed_conditions=10
    )
    setup = detect_developing_setup(
        symbol="BTCUSDT", side=Side.LONG, score=10.0, accepted=False,
        conditions=_checks("volume"), config=cfg, evaluated_at=NOW,
    )
    assert setup is None


def test_rejected_row_within_delta_with_one_missing_condition_is_developing():
    cfg = NearTriggerConfig(score_threshold=70.0, score_delta=20.0, max_missing_conditions=3)
    setup = detect_developing_setup(
        symbol="BTCUSDT", side=Side.LONG, score=55.0, accepted=False,
        conditions=_checks("volume"), config=cfg, evaluated_at=NOW,
    )
    assert setup is not None
    assert setup.symbol == "BTCUSDT"
    assert setup.missing_conditions == ["volume"]
    assert "volume" in setup.projections
    assert setup.detected_at == NOW


def test_too_many_missing_conditions_is_not_developing():
    cfg = NearTriggerConfig(score_threshold=70.0, score_delta=20.0, max_missing_conditions=2)
    setup = detect_developing_setup(
        symbol="BTCUSDT", side=Side.LONG, score=55.0, accepted=False,
        conditions=_checks("volume", "spread", "deadband"), config=cfg, evaluated_at=NOW,
    )
    assert setup is None


def test_zero_missing_conditions_is_not_developing():
    """A rejected row with all CAEMS-native conditions passing was blocked by a
    cross-cutting gate (kill switch, risk, cost) — nothing for the UI to show as
    'missing', so it's excluded."""
    cfg = NearTriggerConfig(score_threshold=70.0, score_delta=20.0)
    setup = detect_developing_setup(
        symbol="BTCUSDT", side=Side.LONG, score=55.0, accepted=False,
        conditions=_checks(), config=cfg, evaluated_at=NOW,
    )
    assert setup is None


def test_rejected_row_with_mostly_passing_gates_is_developing_even_if_score_low():
    cfg = NearTriggerConfig(
        score_threshold=70.0, score_delta=20.0,
        max_missing_conditions=5, min_passed_conditions=5, min_score=0.0,
    )
    setup = detect_developing_setup(
        symbol="BTCUSDT", side=Side.LONG, score=10.0, accepted=False,
        conditions=_checks("volume", "spread"), config=cfg, evaluated_at=NOW,
    )
    assert setup is not None
    assert setup.missing_conditions == ["volume", "spread"]


def test_min_score_40_filters_low_scores():
    cfg = NearTriggerConfig(min_score=40.0, min_passed_conditions=5, max_missing_conditions=5)
    setup = detect_developing_setup(
        symbol="BTCUSDT", side=Side.LONG, score=39.9, accepted=False,
        conditions=_checks("volume"), config=cfg, evaluated_at=NOW,
    )
    assert setup is None
    setup2 = detect_developing_setup(
        symbol="BTCUSDT", side=Side.LONG, score=40.0, accepted=False,
        conditions=_checks("volume"), config=cfg, evaluated_at=NOW,
    )
    assert setup2 is not None

def test_batch_keeps_one_setup_per_symbol():
    cfg = NearTriggerConfig(score_threshold=70.0, score_delta=30.0, max_missing_conditions=3)
    setups = detect_developing_setups(
        [
            ("ETHUSDT", Side.LONG, 60.0, False, _checks("volume")),
            ("ETHUSDT", Side.SHORT, 80.0, False, _checks("spread")),
        ],
        cfg,
        NOW,
    )
    assert len(setups) == 1
    assert setups[0].side is Side.SHORT
    assert setups[0].score == 80.0


def test_batch_detection_ranks_by_score_descending():
    cfg = NearTriggerConfig(score_threshold=70.0, score_delta=30.0, max_missing_conditions=3)
    candidates = [
        ("AAAUSDT", Side.LONG, 45.0, False, _checks("volume")),
        ("BBBUSDT", Side.LONG, 60.0, False, _checks("spread")),
        ("CCCUSDT", Side.LONG, 95.0, True, _checks()),
    ]
    setups = detect_developing_setups(candidates, cfg, NOW)
    assert [s.symbol for s in setups] == ["BBBUSDT", "AAAUSDT"]


def test_developing_setups_service_publish_and_snapshot():
    service = DevelopingSetupsService()
    assert service.snapshot().seq == 0
    assert service.snapshot().setups == []

    cfg = NearTriggerConfig(score_threshold=70.0, score_delta=30.0)
    setup = detect_developing_setup(
        symbol="BTCUSDT", side=Side.LONG, score=55.0, accepted=False,
        conditions=_checks("volume"), config=cfg, evaluated_at=NOW,
    )
    assert setup is not None
    snapshot = service.publish([setup])
    assert snapshot.seq == 1
    assert snapshot.setups == [setup]

    snapshot2 = service.publish([])
    assert snapshot2.seq == 2
    assert snapshot2.setups == []
