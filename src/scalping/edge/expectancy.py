"""Bucketed expectancy, coarse keying only.

PLAN_OF_ACTION.md §6: "buckets stay coarse (side x regime only) until n permits
finer keys" — bucketing finer than that on two symbols starves every bucket of
sample size. Widening the symbol universe (scanner plan) is the real fix, not finer
keys on a thin sample.
"""

from __future__ import annotations

from dataclasses import dataclass

from scalping.domain.models import Side

Regime = str  # e.g. "trend_up", "trend_down", "chop" — defined by the caller


@dataclass
class ExpectancyBucket:
    n: int = 0
    wins: int = 0
    sum_r: float = 0.0
    gross_win_r: float = 0.0
    gross_loss_r: float = 0.0

    def add(self, r_multiple: float) -> None:
        self.n += 1
        self.sum_r += r_multiple
        if r_multiple > 0:
            self.wins += 1
            self.gross_win_r += r_multiple
        else:
            self.gross_loss_r += -r_multiple

    @property
    def win_rate(self) -> float | None:
        return self.wins / self.n if self.n > 0 else None

    @property
    def avg_r(self) -> float | None:
        return self.sum_r / self.n if self.n > 0 else None

    @property
    def profit_factor(self) -> float | None:
        if self.n == 0:
            return None
        if self.gross_loss_r == 0:
            return float("inf") if self.gross_win_r > 0 else None
        return self.gross_win_r / self.gross_loss_r


class ExpectancyStore:
    """Keyed (side, regime) only — see module docstring. `pooled()` exists so
    per-symbol vs pooled expectancy can be compared (PLAN §6: pooling is a
    hypothesis to test, not an assumption)."""

    def __init__(self) -> None:
        self._by_symbol: dict[tuple[str, Side, Regime], ExpectancyBucket] = {}

    def add_trade(self, symbol: str, side: Side, regime: Regime, r_multiple: float) -> None:
        key = (symbol, side, regime)
        self._by_symbol.setdefault(key, ExpectancyBucket()).add(r_multiple)

    def get(self, symbol: str, side: Side, regime: Regime) -> ExpectancyBucket | None:
        return self._by_symbol.get((symbol, side, regime))

    def pooled(self, side: Side, regime: Regime) -> ExpectancyBucket:
        """Expectancy pooled across all symbols for one (side, regime) — a
        hypothesis, not ground truth; compare against `get()` per-symbol before
        trusting this."""
        pooled = ExpectancyBucket()
        for (_, s, r), bucket in self._by_symbol.items():
            if s == side and r == regime:
                pooled.n += bucket.n
                pooled.wins += bucket.wins
                pooled.sum_r += bucket.sum_r
                pooled.gross_win_r += bucket.gross_win_r
                pooled.gross_loss_r += bucket.gross_loss_r
        return pooled
