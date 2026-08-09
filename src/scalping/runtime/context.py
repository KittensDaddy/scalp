"""Build `SymbolEvalContext` from live `SymbolState` — network-free.

Used by the production tick handler so StrategyRunner stays injectable and
unit-testable without a Binance connection.
"""

from __future__ import annotations

from datetime import datetime

from scalping.config.settings import EffectiveConfig
from scalping.costmodel.cost import compute_round_trip_cost, cost_gate_passed
from scalping.domain.models import Side
from scalping.market_data.registry import SymbolState
from scalping.risk.kill_switch import KillSwitch
from scalping.scanner.runner import SymbolEvalContext
from scalping.scoring.features import FeatureRawInputs
from scalping.strategies.caems.engine import (
    MarketQualityFlags,
    MarketSnapshot,
    RiskCostDecision,
)


def indicators_ready(state: SymbolState) -> bool:
    return (
        state.ema_fast_1m.ready
        and state.ema_slow_1m.ready
        and state.ema_fast_5m.ready
        and state.ema_slow_5m.ready
        and state.atr_1m.ready
        and state.volume_median_30.median() is not None
        and state.last_candle_1m is not None
    )


def seconds_to_next_funding(now: datetime) -> float:
    """USDS-M funding lands at 00:00 / 08:00 / 16:00 UTC."""
    hour = now.hour
    next_slot = ((hour // 8) + 1) * 8
    if next_slot >= 24:
        target = now.replace(hour=0, minute=0, second=0, microsecond=0)
        from datetime import timedelta

        target = target + timedelta(days=1)
    else:
        target = now.replace(hour=next_slot, minute=0, second=0, microsecond=0)
    return (target - now).total_seconds()


def build_snapshot(
    state: SymbolState,
    *,
    now: datetime,
    btc_strength: float | None = None,
) -> MarketSnapshot | None:
    if not indicators_ready(state):
        return None
    candle = state.last_candle_1m
    assert candle is not None
    bt = state.last_book_ticker
    spread = bt.spread_bps if bt is not None else 99.0
    median = state.volume_median_30.median()
    assert median is not None
    return MarketSnapshot(
        symbol=state.symbol,
        ema_fast_1m=state.ema_fast_1m.value,
        ema_slow_1m=state.ema_slow_1m.value,
        ema_fast_5m=state.ema_fast_5m.value,
        ema_slow_5m=state.ema_slow_5m.value,
        atr14_1m=state.atr_1m.value,
        completed_close=candle.close,
        last_bar_high=candle.high,
        last_bar_low=candle.low,
        completed_quote_volume=candle.quote_volume,
        volume_median_30=median,
        spread_bps=spread,
        seconds_to_next_funding=seconds_to_next_funding(now),
        btc_strength=btc_strength,
    )


def _stop_distance(snapshot: MarketSnapshot, config: EffectiveConfig) -> float:
    execution_floor = (
        3 * (snapshot.spread_bps / 10_000 * snapshot.completed_close)
        + 2 * config.exits.slippage_buffer
    )
    return max(snapshot.atr14_1m, execution_floor)


def _expected_edge_bps(snapshot: MarketSnapshot, config: EffectiveConfig) -> float:
    stop_d = _stop_distance(snapshot, config)
    if snapshot.completed_close <= 0:
        return 0.0
    return (config.frozen.take_profit_r * stop_d / snapshot.completed_close) * 10_000.0


def build_feature_raw(
    *,
    side: Side,
    snapshot: MarketSnapshot,
    config: EffectiveConfig,
    evaluated_at: datetime,
    stale: bool,
    btc_ema_fast_1m: float | None = None,
    btc_ema_slow_1m: float | None = None,
) -> FeatureRawInputs:
    cost = compute_round_trip_cost(
        cost_cfg=config.cost, spread_bps=snapshot.spread_bps, is_maker_entry=True
    )
    edge = _expected_edge_bps(snapshot, config)
    return FeatureRawInputs(
        side=side,
        entry_reference=snapshot.completed_close,
        btc_ema_fast_1m=btc_ema_fast_1m,
        btc_ema_slow_1m=btc_ema_slow_1m,
        spread_bps=snapshot.spread_bps,
        expected_cost_bps=cost.total_bps,
        expected_edge_bps=edge,
        liquidity_percentile=0.5,
        historical_edge_frac=0.0,
        confirmations_frac=0.5,
        stale=stale,
        evaluated_at=evaluated_at,
    )


def build_risk_cost(
    *,
    snapshot: MarketSnapshot,
    config: EffectiveConfig,
    risk_approved: bool = True,
) -> RiskCostDecision:
    cost = compute_round_trip_cost(
        cost_cfg=config.cost, spread_bps=snapshot.spread_bps, is_maker_entry=True
    )
    edge = _expected_edge_bps(snapshot, config)
    passed = cost_gate_passed(
        expected_gross_edge_bps=edge,
        cost=cost,
        cost_edge_multiplier=config.cost.cost_edge_multiplier,
    )
    return RiskCostDecision(
        risk_approved=risk_approved,
        cost_gate_passed=passed,
        edge_sufficient=passed,
    )


def build_eval_context(
    state: SymbolState,
    *,
    config: EffectiveConfig,
    evaluated_at: datetime,
    kill_switch: KillSwitch | None = None,
    symbol_class: str = "default",
    btc_strength: float | None = None,
    btc_ema_fast_1m: float | None = None,
    btc_ema_slow_1m: float | None = None,
    risk_approved: bool = True,
) -> SymbolEvalContext | None:
    snapshot = build_snapshot(state, now=evaluated_at, btc_strength=btc_strength)
    if snapshot is None:
        return None
    bt = state.last_book_ticker
    flags = MarketQualityFlags(
        kill_switch_engaged=bool(kill_switch and kill_switch.killed),
        symbol_disabled=config.symbol_meta.disabled,
        shorts_enabled=config.symbol_meta.shorts_enabled,
        stale_market_data=False,
        invalid_book=bt is None,
        liquidity_too_low=False,
    )
    risk_cost = build_risk_cost(
        snapshot=snapshot, config=config, risk_approved=risk_approved
    )
    return SymbolEvalContext(
        symbol=state.symbol,
        symbol_class=symbol_class,
        state=state,
        snapshot=snapshot,
        feature_raw_by_side={
            Side.LONG: build_feature_raw(
                side=Side.LONG,
                snapshot=snapshot,
                config=config,
                evaluated_at=evaluated_at,
                stale=False,
                btc_ema_fast_1m=btc_ema_fast_1m,
                btc_ema_slow_1m=btc_ema_slow_1m,
            ),
            Side.SHORT: build_feature_raw(
                side=Side.SHORT,
                snapshot=snapshot,
                config=config,
                evaluated_at=evaluated_at,
                stale=False,
                btc_ema_fast_1m=btc_ema_fast_1m,
                btc_ema_slow_1m=btc_ema_slow_1m,
            ),
        },
        flags=flags,
        risk_cost_by_side={Side.LONG: risk_cost, Side.SHORT: risk_cost},
    )
