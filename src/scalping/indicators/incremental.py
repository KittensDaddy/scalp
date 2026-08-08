"""Incremental (O(1) per bar) indicators.

SCANNER_DASHBOARD_PLAN.md §A audit item #2 and §J: indicators must be O(1) per bar,
not recomputed over full history on every tick — full recompute does not scale to a
multi-symbol universe. Each class here consumes one bar/value at a time and holds only
the state it needs, with a `.value` property mirroring what a batch computation over
the same input sequence would produce (verified in tests/unit/test_indicators.py).
"""

from __future__ import annotations

from collections import deque


class EMA:
    """Exponential moving average, seeded with a simple average of the first
    `period` values (standard EMA convention), then recursively updated.
    """

    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        self.period = period
        self._alpha = 2.0 / (period + 1.0)
        self._seed_buf: list[float] = []
        self._value: float | None = None

    def update(self, price: float) -> float | None:
        if self._value is not None:
            self._value = (price - self._value) * self._alpha + self._value
            return self._value
        self._seed_buf.append(price)
        if len(self._seed_buf) < self.period:
            return None
        self._value = sum(self._seed_buf) / self.period
        return self._value

    @property
    def value(self) -> float | None:
        return self._value

    @property
    def ready(self) -> bool:
        return self._value is not None


class ATR:
    """Average True Range, Wilder smoothing (matches the standard ATR14 convention
    used throughout strategy-caems.md)."""

    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        self.period = period
        self._prev_close: float | None = None
        self._tr_seed: list[float] = []
        self._value: float | None = None

    def update(self, high: float, low: float, close: float) -> float | None:
        if self._prev_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - self._prev_close), abs(low - self._prev_close))
        self._prev_close = close

        if self._value is not None:
            self._value = (self._value * (self.period - 1) + tr) / self.period
            return self._value

        self._tr_seed.append(tr)
        if len(self._tr_seed) < self.period:
            return None
        self._value = sum(self._tr_seed) / self.period
        return self._value

    @property
    def value(self) -> float | None:
        return self._value

    @property
    def ready(self) -> bool:
        return self._value is not None


class RollingMedian:
    """Rolling median of the prior N *completed* values (strategy-caems.md: volume
    gate uses the median of the prior 30 completed 1m quote-volumes — the current bar
    is never included).
    """

    def __init__(self, window: int) -> None:
        if window < 1:
            raise ValueError("window must be >= 1")
        self.window = window
        self._buf: deque[float] = deque(maxlen=window)

    def median(self) -> float | None:
        """Median of values seen so far (before the next `update`)."""
        if not self._buf:
            return None
        s = sorted(self._buf)
        n = len(s)
        mid = n // 2
        if n % 2:
            return s[mid]
        return (s[mid - 1] + s[mid]) / 2

    def update(self, value: float) -> None:
        self._buf.append(value)

    @property
    def ready(self) -> bool:
        return len(self._buf) >= self.window


class RSI:
    """Wilder RSI, standard 0-100 scale."""

    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        self.period = period
        self._prev_close: float | None = None
        self._gain_seed: list[float] = []
        self._loss_seed: list[float] = []
        self._avg_gain: float | None = None
        self._avg_loss: float | None = None

    def update(self, close: float) -> float | None:
        if self._prev_close is None:
            self._prev_close = close
            return None
        change = close - self._prev_close
        self._prev_close = close
        gain = max(change, 0.0)
        loss = max(-change, 0.0)

        if self._avg_gain is not None:
            self._avg_gain = (self._avg_gain * (self.period - 1) + gain) / self.period
            self._avg_loss = (self._avg_loss * (self.period - 1) + loss) / self.period  # type: ignore[operator]
        else:
            self._gain_seed.append(gain)
            self._loss_seed.append(loss)
            if len(self._gain_seed) < self.period:
                return None
            self._avg_gain = sum(self._gain_seed) / self.period
            self._avg_loss = sum(self._loss_seed) / self.period

        if self._avg_loss == 0:
            return 100.0
        rs = self._avg_gain / self._avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    @property
    def ready(self) -> bool:
        return self._avg_gain is not None


def strength(ema_fast: float, ema_slow: float, atr: float) -> float:
    """strategy-caems.md §Strength: (EMA12_1m - EMA48_1m) / ATR14_1m."""
    return (ema_fast - ema_slow) / atr
