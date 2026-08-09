"""UTC day/week rollover detection for the drawdown machine.

`DrawdownState` deliberately does not auto-reset on wall-clock rollover — its
docstring puts that on the caller so the behavior stays explicit and testable
without freezing time. This is that caller: a tiny pure tracker the trading loop
ticks, which reports whether a boundary was crossed since the last call.

Without it, `daily_loss_cap_r` is not a daily cap at all — the first day that
breaches it halts entries for the rest of the campaign.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from scalping.risk.drawdown import DrawdownState


@dataclass(frozen=True)
class PeriodRollover:
    daily: bool
    weekly: bool

    def __bool__(self) -> bool:
        return self.daily or self.weekly


@dataclass
class PeriodTracker:
    """Tracks the UTC day and ISO week last seen.

    The first call establishes the baseline and reports no rollover — a process
    starting mid-day must not wipe the drawdown state it just restored from the
    trade record.
    """

    last_day: tuple[int, int, int] | None = None
    last_week: tuple[int, int] | None = None

    @staticmethod
    def _keys(now: datetime) -> tuple[tuple[int, int, int], tuple[int, int]]:
        utc = now.astimezone(UTC) if now.tzinfo is not None else now.replace(tzinfo=UTC)
        iso = utc.isocalendar()
        return (utc.year, utc.month, utc.day), (iso.year, iso.week)

    def observe(self, now: datetime) -> PeriodRollover:
        day, week = self._keys(now)
        first_call = self.last_day is None
        rolled_day = not first_call and day != self.last_day
        rolled_week = self.last_week is not None and week != self.last_week
        self.last_day = day
        self.last_week = week
        return PeriodRollover(daily=rolled_day, weekly=rolled_week)

    def apply(self, drawdown: DrawdownState, now: datetime) -> PeriodRollover:
        """Observe `now` and reset whichever periods rolled over."""
        rollover = self.observe(now)
        if rollover.daily:
            drawdown.reset_daily()
        if rollover.weekly:
            drawdown.reset_weekly()
        return rollover
