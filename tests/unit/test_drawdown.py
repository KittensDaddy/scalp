from __future__ import annotations

import pytest

from scalping.risk.drawdown import DrawdownState


def test_record_trade_updates_daily_and_weekly():
    dd = DrawdownState()
    dd.record_trade(1.5)
    dd.record_trade(-0.5)
    assert dd.daily_r == pytest.approx(1.0)
    assert dd.weekly_r == pytest.approx(1.0)


def test_daily_limit_breached_boundary():
    dd = DrawdownState()
    dd.record_trade(-3.0)
    assert dd.daily_limit_breached(3.0) is True
    assert dd.daily_limit_breached(3.01) is False


def test_reset_daily_does_not_affect_weekly():
    dd = DrawdownState()
    dd.record_trade(-2.0)
    dd.reset_daily()
    assert dd.daily_r == 0.0
    assert dd.weekly_r == -2.0


def test_max_drawdown_r_tracks_peak_to_trough():
    dd = DrawdownState()
    for r in [2.0, 1.0, -4.0, 1.0]:
        dd.record_trade(r)
    # cumulative: 2, 3, -1, 0 ; peak 3, trough -1 -> max_dd = 4
    assert dd.max_drawdown_r() == pytest.approx(4.0)
