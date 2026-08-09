"""Active-trade monitoring unit tests — S8: MAE/MFE, health labels, lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scalping.domain.models import HealthLabel, Position, Side, TradeEventType
from scalping.monitoring.active_trades import (
    ActiveTradeService,
    classify_health,
    reject_probability_fields,
    unrealized_r,
    update_mae_mfe,
)

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def _long_position(**kwargs) -> Position:
    base = dict(
        symbol="BTCUSDT",
        side=Side.LONG,
        entry_price=100.0,
        quantity=1.0,
        stop_price=99.0,  # 1R = 1.0
        take_profit_price=101.35,
        opened_at=NOW,
    )
    base.update(kwargs)
    return Position(**base)


def test_update_mae_mfe_tracks_adverse_and_favorable():
    mae, mfe = update_mae_mfe(0.0, 0.0, 0.0)
    assert mae == 0.0 and mfe == 0.0
    mae, mfe = update_mae_mfe(mae, mfe, -0.4)
    assert mae == pytest.approx(0.4) and mfe == 0.0
    mae, mfe = update_mae_mfe(mae, mfe, 0.7)
    assert mae == pytest.approx(0.4) and mfe == pytest.approx(0.7)
    mae, mfe = update_mae_mfe(mae, mfe, -0.2)
    assert mae == pytest.approx(0.4) and mfe == pytest.approx(0.7)


def test_unrealized_r_long_and_short():
    assert unrealized_r(
        side=Side.LONG, entry_price=100.0, stop_price=99.0, price=100.5
    ) == pytest.approx(0.5)
    assert unrealized_r(
        side=Side.SHORT, entry_price=100.0, stop_price=101.0, price=99.5
    ) == pytest.approx(0.5)


def test_classify_health_geometry_only():
    assert classify_health(distance_to_stop=0.1, distance_to_tp=1.0, unrealized=-0.9) == (
        HealthLabel.NEAR_STOP
    )
    assert classify_health(distance_to_stop=1.0, distance_to_tp=0.2, unrealized=1.0) == (
        HealthLabel.NEAR_TP
    )
    assert classify_health(distance_to_stop=0.8, distance_to_tp=0.8, unrealized=-0.2) == (
        HealthLabel.AT_RISK
    )
    assert classify_health(distance_to_stop=0.8, distance_to_tp=0.8, unrealized=0.3) == (
        HealthLabel.HEALTHY
    )


def test_reject_probability_fields():
    reject_probability_fields({"old_score": 70, "new_score": 80})
    with pytest.raises(ValueError, match="probability"):
        reject_probability_fields({"win_probability": 0.62})
    with pytest.raises(ValueError, match="probability"):
        reject_probability_fields({"chance_of_tp": 0.4})


def test_full_paper_trade_lifecycle_timeline():
    """Acceptance: full timeline reproduced for a paper trade end-to-end."""
    service = ActiveTradeService()
    pos = _long_position()

    trade, event, snap = service.open_trade(
        trade_id="t1", position=pos, current_price=100.0, score=88.0, ts=NOW
    )
    assert event.event_type is TradeEventType.OPENED
    assert snap.seq == 1
    assert trade.health is HealthLabel.HEALTHY
    assert len(snap.positions) == 1

    _, event, snap = service.mark_protected("t1", ts=NOW, t_protection_ms=120.0)
    assert event.event_type is TradeEventType.PROTECTED
    assert service.get("t1").protected is True

    trade, snap = service.update_price("t1", 99.6)
    assert trade.unrealized_r == pytest.approx(-0.4)
    assert trade.mae_r == pytest.approx(0.4)
    assert trade.health is HealthLabel.AT_RISK

    trade, snap = service.update_price("t1", 100.8)
    assert trade.mfe_r == pytest.approx(0.8)
    assert trade.unrealized_r == pytest.approx(0.8)

    _, event, snap = service.move_breakeven("t1", new_stop=100.0, ts=NOW)
    assert event.event_type is TradeEventType.BREAKEVEN_MOVED
    assert service.get("t1").breakeven_moved is True
    assert service.get("t1").stop_price == 100.0

    _, event, snap = service.update_score(
        "t1", score=72.0, ts=NOW, explanation="momentum faded"
    )
    assert event is not None
    assert event.event_type is TradeEventType.SCORE_CHANGED
    assert "probability" not in event.payload

    trade, event, snap = service.close_trade(
        "t1", exit_price=101.35, exit_reason="TAKE_PROFIT", ts=NOW
    )
    assert event.event_type is TradeEventType.CLOSED
    assert snap.positions == []  # no longer open
    assert trade.closed is True

    types = [e.event_type for e in service.events("t1")]
    assert types == [
        TradeEventType.OPENED,
        TradeEventType.PROTECTED,
        TradeEventType.BREAKEVEN_MOVED,
        TradeEventType.SCORE_CHANGED,
        TradeEventType.CLOSED,
    ]


def test_service_rejects_probability_payloads():
    from scalping.domain.models import TradeEvent

    service = ActiveTradeService()
    service.open_trade(trade_id="t1", position=_long_position(), ts=NOW)
    with pytest.raises(ValueError, match="probability"):
        service._append_event(
            TradeEvent(
                trade_id="t1",
                symbol="BTCUSDT",
                event_type=TradeEventType.SCORE_CHANGED,
                ts=NOW,
                payload={"win_probability": 0.55},
            )
        )


def test_score_unchanged_does_not_emit_event():
    service = ActiveTradeService()
    service.open_trade(trade_id="t1", position=_long_position(), score=80.0, ts=NOW)
    _, event, snap = service.update_score("t1", score=80.0, ts=NOW)
    assert event is None
    assert snap.seq == 1  # no bump
    assert [e.event_type for e in service.events("t1")] == [TradeEventType.OPENED]


def test_near_stop_health_on_price_update():
    service = ActiveTradeService()
    service.open_trade(trade_id="t1", position=_long_position(), ts=NOW)
    trade, _ = service.update_price("t1", 99.2)  # 0.2R to stop
    assert trade.health is HealthLabel.NEAR_STOP
    assert trade.distance_to_stop_r == pytest.approx(0.2)
