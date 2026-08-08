from __future__ import annotations

from scalping.config.settings import RiskConfig
from scalping.domain.models import RejectionReason, Side
from scalping.risk.drawdown import DrawdownState
from scalping.risk.engine import RiskEngine, RiskRequest


def _request(**overrides) -> RiskRequest:
    defaults = dict(
        symbol="BTCUSDT", symbol_class="btc", side=Side.LONG, entry=100.0, stop=99.0,
        equity=10_000.0, available_depth=1_000_000.0, bar_volume=1_000_000.0,
        exchange_max_notional=1_000_000.0,
    )
    defaults.update(overrides)
    return RiskRequest(**defaults)


def test_approves_within_limits():
    engine = RiskEngine()
    approval = engine.evaluate(_request(), RiskConfig())
    assert approval.approved is True
    assert approval.size is not None


def test_daily_drawdown_limit_blocks():
    dd = DrawdownState()
    dd.record_trade(-3.5)
    engine = RiskEngine(drawdown=dd)
    approval = engine.evaluate(_request(), RiskConfig(daily_loss_cap_r=3.0))
    assert approval.approved is False
    assert approval.reason == RejectionReason.DRAW_DOWN_LIMIT


def test_weekly_drawdown_limit_blocks():
    dd = DrawdownState()
    dd.weekly_r = -7.0
    engine = RiskEngine(drawdown=dd)
    approval = engine.evaluate(_request(), RiskConfig(weekly_loss_cap_r=6.0))
    assert approval.approved is False
    assert approval.reason == RejectionReason.DRAW_DOWN_LIMIT


def test_max_positions_total_blocks():
    engine = RiskEngine()
    engine.on_position_opened("btc")
    engine.on_position_opened("eth")
    approval = engine.evaluate(_request(symbol_class="major_alt"), RiskConfig(max_positions_total=2))
    assert approval.approved is False
    assert approval.reason == RejectionReason.RISK_LIMIT


def test_max_positions_in_class_blocks():
    engine = RiskEngine()
    engine.on_position_opened("btc")
    approval = engine.evaluate(
        _request(symbol_class="btc"), RiskConfig(max_positions_total=5, max_positions_in_class=1)
    )
    assert approval.approved is False
    assert approval.reason == RejectionReason.RISK_LIMIT


def test_position_closed_frees_up_class_slot():
    engine = RiskEngine()
    engine.on_position_opened("btc")
    engine.on_position_closed("btc")
    approval = engine.evaluate(
        _request(symbol_class="btc"), RiskConfig(max_positions_total=5, max_positions_in_class=1)
    )
    assert approval.approved is True


def test_drawdown_recovers_after_reset():
    dd = DrawdownState()
    dd.record_trade(-5.0)
    engine = RiskEngine(drawdown=dd)
    cfg = RiskConfig(daily_loss_cap_r=3.0)
    assert engine.evaluate(_request(), cfg).approved is False
    dd.reset_daily()
    assert engine.evaluate(_request(), cfg).approved is True
