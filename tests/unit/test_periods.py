"""UTC period rollover for the daily/weekly loss caps."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scalping.risk.drawdown import DrawdownState
from scalping.runtime.periods import PeriodTracker

# A Wednesday.
NOON = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def test_first_observation_does_not_reset():
    """A process starting mid-day must not wipe the drawdown it just restored."""
    dd = DrawdownState()
    dd.record_trade(-2.0)
    tracker = PeriodTracker()

    rollover = tracker.apply(dd, NOON)

    assert not rollover
    assert dd.daily_r == -2.0
    assert dd.weekly_r == -2.0


def test_same_day_ticks_do_not_reset():
    dd = DrawdownState()
    tracker = PeriodTracker()
    tracker.apply(dd, NOON)
    dd.record_trade(-1.5)

    tracker.apply(dd, NOON + timedelta(hours=6))

    assert dd.daily_r == -1.5


def test_next_day_resets_daily_but_not_weekly():
    dd = DrawdownState()
    tracker = PeriodTracker()
    tracker.apply(dd, NOON)
    dd.record_trade(-3.0)

    rollover = tracker.apply(dd, NOON + timedelta(days=1))

    assert rollover.daily is True
    assert rollover.weekly is False
    assert dd.daily_r == 0.0
    assert dd.weekly_r == -3.0


def test_next_week_resets_both():
    dd = DrawdownState()
    tracker = PeriodTracker()
    tracker.apply(dd, NOON)
    dd.record_trade(-5.0)

    # Wednesday -> following Monday crosses both boundaries.
    rollover = tracker.apply(dd, NOON + timedelta(days=5))

    assert rollover.daily is True
    assert rollover.weekly is True
    assert dd.daily_r == 0.0
    assert dd.weekly_r == 0.0


def test_daily_cap_stops_being_permanent_once_rolled():
    """Without a rollover the first day to breach the cap halts the campaign."""
    dd = DrawdownState()
    tracker = PeriodTracker()
    tracker.apply(dd, NOON)
    dd.record_trade(-3.5)
    assert dd.daily_limit_breached(3.0) is True

    tracker.apply(dd, NOON + timedelta(days=1))

    assert dd.daily_limit_breached(3.0) is False


def test_trade_history_survives_resets_for_max_drawdown():
    dd = DrawdownState()
    tracker = PeriodTracker()
    tracker.apply(dd, NOON)
    dd.record_trade(-2.0)
    tracker.apply(dd, NOON + timedelta(days=1))
    dd.record_trade(-1.0)

    # Campaign-level max drawdown spans the reset boundary.
    assert dd.max_drawdown_r() == 3.0


def test_naive_datetimes_are_treated_as_utc():
    dd = DrawdownState()
    tracker = PeriodTracker()
    tracker.apply(dd, NOON.replace(tzinfo=None))
    dd.record_trade(-1.0)

    rollover = tracker.apply(dd, (NOON + timedelta(days=1)).replace(tzinfo=None))

    assert rollover.daily is True
