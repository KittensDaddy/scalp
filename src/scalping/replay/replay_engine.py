"""Event replay — PLAN_OF_ACTION.md phase 9.

Drives the CAEMS engine over a recorded candle sequence in strict chronological
order, the same evaluation path the live pipeline uses (via
`scalping.backtest.candle_backtester`, which this module wraps rather than
duplicates — replay and the candle-level sanity backtester are the same mechanism
run for different purposes). Two properties are load-bearing and checked by
`assert_prefix_consistent` in tests: no look-ahead (a signal at time t must not
depend on data after t) and determinism (same input -> same output, always).
"""

from __future__ import annotations

from scalping.backtest.candle_backtester import BacktestResult, run_candle_backtest
from scalping.config.frozen import FrozenParams
from scalping.config.settings import EffectiveConfig
from scalping.domain.models import Candle, Side


def run_replay(
    candles_1m: list[Candle],
    candles_5m: list[Candle],
    config: EffectiveConfig,
    frozen: FrozenParams | None = None,
    sides: tuple[Side, ...] = (Side.LONG, Side.SHORT),
) -> BacktestResult:
    return run_candle_backtest(candles_1m, candles_5m, config, frozen, sides)


class LookaheadViolation(Exception):
    pass


def assert_prefix_consistent(full: BacktestResult, prefix: BacktestResult, cutoff_time) -> None:
    """A trade that fully closed at or before `cutoff_time` in the prefix run must
    appear identically (same entry/exit price, same R, same reason) in the full
    run. If it doesn't, the full run's extra future data changed a decision that
    should have already been settled by `cutoff_time` — a look-ahead violation.
    """
    full_by_key = {
        (t.side, t.entry_time, t.exit_time): t for t in full.trades if t.exit_time <= cutoff_time
    }
    for t in prefix.trades:
        if t.exit_time > cutoff_time:
            continue
        key = (t.side, t.entry_time, t.exit_time)
        match = full_by_key.get(key)
        if match is None:
            raise LookaheadViolation(
                f"prefix trade {key} closed by cutoff but missing from full run "
                f"(full run's extra data changed the outcome)"
            )
        if (match.entry_price, match.exit_price, match.r_multiple, match.exit_reason) != (
            t.entry_price, t.exit_price, t.r_multiple, t.exit_reason
        ):
            raise LookaheadViolation(f"prefix trade {key} differs from full run: {t} vs {match}")
