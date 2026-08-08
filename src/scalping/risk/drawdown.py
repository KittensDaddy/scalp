"""Daily/weekly drawdown state machine.

Tracks cumulative realized R for the current day and week. Once either cap is
breached, new entries are refused (DRAW_DOWN_LIMIT) until an explicit period reset —
this module does not auto-reset on wall-clock rollover; the caller (trading loop)
calls `reset_daily`/`reset_weekly` at the appropriate boundary so behavior is
explicit and testable without freezing time.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DrawdownState:
    daily_r: float = 0.0
    weekly_r: float = 0.0
    trade_r_history: list[float] = field(default_factory=list)

    def record_trade(self, r_multiple: float) -> None:
        self.daily_r += r_multiple
        self.weekly_r += r_multiple
        self.trade_r_history.append(r_multiple)

    def reset_daily(self) -> None:
        self.daily_r = 0.0

    def reset_weekly(self) -> None:
        self.weekly_r = 0.0

    def daily_limit_breached(self, daily_loss_cap_r: float) -> bool:
        return self.daily_r <= -abs(daily_loss_cap_r)

    def weekly_limit_breached(self, weekly_loss_cap_r: float) -> bool:
        return self.weekly_r <= -abs(weekly_loss_cap_r)

    def max_drawdown_r(self) -> float:
        """Peak-to-trough drawdown over the recorded trade sequence, in R."""
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for r in self.trade_r_history:
            cumulative += r
            peak = max(peak, cumulative)
            max_dd = max(max_dd, peak - cumulative)
        return max_dd
