"""Candle backtester — gross-signal sanity check ONLY.

PLAN_OF_ACTION.md §5: "CAEMS uses GTX maker entries; a candle backtester cannot
model queue position, maker fill probability, or intrabar stop-outs. The
backtester's role is now explicitly gross-signal sanity check only. It contributes
zero evidence toward the go-live decision; only paper/testnet forward data counts."

`BacktestResult.sanity_only` is always `True` and is the single source of truth the
UI banner (DASHBOARD_STRATEGY_LAB.md §2) reads from — it is not restated as a
hardcoded string anywhere else, so there is exactly one place that could ever make
this claim false.

Fill/exit model (approximated, per the docstring above): entry at the next bar's
open; among subsequent bars up to the time stop, stop and take-profit are checked
against each bar's high/low, first-touched-wins; if neither touches, exit at the
time-stop bar's close.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from scalping.config.frozen import FrozenParams
from scalping.config.settings import EffectiveConfig
from scalping.costmodel.cost import compute_round_trip_cost
from scalping.domain.models import Candle, Side
from scalping.execution.protection import breakeven_move_allowed, compute_breakeven_stop
from scalping.indicators.incremental import ATR, EMA, RollingMedian
from scalping.risk.drawdown import DrawdownState
from scalping.strategies.caems.engine import (
    MarketQualityFlags,
    MarketSnapshot,
    RiskCostDecision,
    evaluate,
)

SANITY_ONLY_BANNER = (
    "Candle-level simulation. Maker fill probability, queue position and intrabar "
    "stop sequencing are approximated. This result is NOT evidence of live edge — "
    "see paper campaign."
)


@dataclass(frozen=True)
class BacktestTrade:
    side: Side
    entry_time: object
    exit_time: object
    entry_price: float
    exit_price: float
    r_multiple: float
    exit_reason: str


@dataclass
class BacktestResult:
    trades: list[BacktestTrade] = field(default_factory=list)
    rejection_counts: dict[str, int] = field(default_factory=dict)
    sanity_only: bool = True
    banner: str = SANITY_ONLY_BANNER

    @property
    def n(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> float | None:
        if not self.trades:
            return None
        return sum(1 for t in self.trades if t.r_multiple > 0) / len(self.trades)

    @property
    def net_expectancy_r(self) -> float | None:
        if not self.trades:
            return None
        return sum(t.r_multiple for t in self.trades) / len(self.trades)

    @property
    def profit_factor(self) -> float | None:
        wins = sum(t.r_multiple for t in self.trades if t.r_multiple > 0)
        losses = -sum(t.r_multiple for t in self.trades if t.r_multiple < 0)
        if not self.trades:
            return None
        if losses == 0:
            return float("inf") if wins > 0 else None
        return wins / losses

    @property
    def max_drawdown_r(self) -> float:
        dd = DrawdownState()
        for t in self.trades:
            dd.record_trade(t.r_multiple)
        return dd.max_drawdown_r()


def _nearest_5m_ema(
    candle_1m: Candle, candles_5m: list[Candle], idx_5m: int, ema_fast: EMA, ema_slow: EMA
) -> tuple[float | None, float | None, int]:
    """Advance the 5m EMA state to the latest 5m candle whose close_time <= the
    current 1m candle's close_time, returning (fast, slow, new_idx_5m)."""
    while idx_5m < len(candles_5m) and candles_5m[idx_5m].close_time <= candle_1m.close_time:
        ema_fast.update(candles_5m[idx_5m].close)
        ema_slow.update(candles_5m[idx_5m].close)
        idx_5m += 1
    return ema_fast.value, ema_slow.value, idx_5m


def run_candle_backtest(
    candles_1m: list[Candle],
    candles_5m: list[Candle],
    config: EffectiveConfig,
    frozen: FrozenParams | None = None,
    sides: tuple[Side, ...] = (Side.LONG, Side.SHORT),
) -> BacktestResult:
    """Gross-signal sanity check — see module docstring. Risk/cost gates are
    bypassed (always-approved) because this backtester tests signal generation and
    exit geometry only, not execution economics; those are proven on paper/testnet."""
    frozen = frozen or FrozenParams()
    result = BacktestResult()

    ema_fast_1m = EMA(frozen.ema_fast_1m)
    ema_slow_1m = EMA(frozen.ema_slow_1m)
    ema_fast_5m = EMA(frozen.ema_fast_5m)
    ema_slow_5m = EMA(frozen.ema_slow_5m)
    atr = ATR(frozen.atr_period_1m)
    vol_median = RollingMedian(frozen.volume_median_bars)
    idx_5m = 0

    round_trip_cost_bps = compute_round_trip_cost(cost_cfg=config.cost, spread_bps=0.0).total_bps

    open_trade: dict[Side, dict] = {}

    def close_trade(
        side: Side, exit_price: float, exit_reason: str,
        entry_time, entry_price: float, stop_distance: float, exit_time,
    ) -> None:
        r = (exit_price - entry_price) / stop_distance
        if side is Side.SHORT:
            r = -r
        result.trades.append(
            BacktestTrade(
                side=side, entry_time=entry_time, exit_time=exit_time, entry_price=entry_price,
                exit_price=exit_price, r_multiple=r, exit_reason=exit_reason,
            )
        )

    for i, candle in enumerate(candles_1m):
        f1 = ema_fast_1m.update(candle.close)
        s1 = ema_slow_1m.update(candle.close)
        a = atr.update(candle.high, candle.low, candle.close)
        median_before = vol_median.median()
        vol_median.update(candle.quote_volume)
        f5, s5, idx_5m = _nearest_5m_ema(candle, candles_5m, idx_5m, ema_fast_5m, ema_slow_5m)

        # -- manage any open trades against this bar's range first --
        for side in list(open_trade.keys()):
            pos = open_trade[side]
            if config.exits.be_enabled and not pos["be_moved"]:
                favorable = candle.high if side is Side.LONG else candle.low
                unrealized_r = (favorable - pos["entry"]) / pos["stop_distance"]
                if side is Side.SHORT:
                    unrealized_r = -unrealized_r
                if unrealized_r >= config.exits.be_trigger_r:
                    offset_price_units = round_trip_cost_bps / 10_000 * pos["entry"]
                    new_stop = compute_breakeven_stop(
                        side=side, entry_price=pos["entry"],
                        round_trip_cost_price_units=offset_price_units,
                    )
                    if breakeven_move_allowed(
                        side=side, current_stop=pos["stop"], new_stop=new_stop, already_moved=False
                    ):
                        pos["stop"] = new_stop
                        pos["be_moved"] = True

            args = (pos["entry_time"], pos["entry"], pos["stop_distance"])
            hit_stop = (
                candle.low <= pos["stop"] if side is Side.LONG else candle.high >= pos["stop"]
            )
            hit_tp = candle.high >= pos["tp"] if side is Side.LONG else candle.low <= pos["tp"]
            timed_out = candle.close_time - pos["entry_time"] >= timedelta(
                seconds=frozen.time_stop_s
            )
            if hit_stop:
                # ambiguous-intrabar-order case (both stop and TP hit this bar) is
                # folded in here too: candle data cannot resolve which came first,
                # so conservatively assume the worse outcome per sanity-only mandate
                close_trade(side, pos["stop"], "STOP", *args, candle.close_time)
                del open_trade[side]
            elif hit_tp:
                close_trade(side, pos["tp"], "TAKE_PROFIT", *args, candle.close_time)
                del open_trade[side]
            elif timed_out:
                close_trade(side, candle.close, "TIME_STOP", *args, candle.close_time)
                del open_trade[side]

        if None in (f1, s1, a, f5, s5) or median_before is None:
            continue
        if i + 1 >= len(candles_1m):
            continue  # no next bar to enter on

        snapshot = MarketSnapshot(
            symbol=candle.symbol, ema_fast_1m=f1, ema_slow_1m=s1,
            ema_fast_5m=f5, ema_slow_5m=s5, atr14_1m=a,
            completed_close=candle.close, last_bar_high=candle.high, last_bar_low=candle.low,
            completed_quote_volume=candle.quote_volume, volume_median_30=median_before,
            spread_bps=0.0, seconds_to_next_funding=10_000.0,
        )
        for side in sides:
            if side in open_trade:
                continue
            evaluation, signal = evaluate(
                side=side, snapshot=snapshot, config=config, frozen=frozen,
                config_hash="backtest", evaluated_at=candle.close_time,
                flags=MarketQualityFlags(),
                risk_cost=RiskCostDecision(risk_approved=True),
            )
            if not evaluation.accepted:
                reason = evaluation.rejection_reason
                key = reason.value if reason else "unknown"
                result.rejection_counts[key] = result.rejection_counts.get(key, 0) + 1
                continue
            assert signal is not None
            next_bar = candles_1m[i + 1]
            entry_price = next_bar.open
            stop_distance = abs(signal.entry_reference - signal.stop)
            stop = entry_price - stop_distance if side is Side.LONG else entry_price + stop_distance
            tp = (
                entry_price + frozen.take_profit_r * stop_distance
                if side is Side.LONG
                else entry_price - frozen.take_profit_r * stop_distance
            )
            open_trade[side] = {
                "entry": entry_price, "stop": stop, "tp": tp,
                "entry_time": next_bar.close_time, "stop_distance": stop_distance,
                "be_moved": False,
            }

    return result


__all__ = ["SANITY_ONLY_BANNER", "BacktestResult", "BacktestTrade", "run_candle_backtest"]
