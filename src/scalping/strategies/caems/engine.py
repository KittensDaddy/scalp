"""CAEMS v2 signal engine — strategy-caems.md, implemented verbatim.

Every LONG condition (1-12) and its SHORT mirror is checked in the document's own
order; the first failing condition determines the rejection reason, and every call
(whether it accepts or rejects) is returned as a :class:`StrategyEvaluation` with
`strength` populated, per "Logged on every evaluation (signals AND rejections)".

Conditions 11 (risk gate) and 12 (cost gate) are owned by the risk engine (P4) and
cost model (P5) respectively; this module takes their decisions as inputs rather than
recomputing them, keeping the Strategy -> Risk boundary from PLAN_OF_ACTION.md §3 a
hard one. Everything upstream of risk/cost — the 10 CAEMS-native gates plus the
reserved BTC veto — is fully owned here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from scalping.config.frozen import FrozenParams
from scalping.config.settings import EffectiveConfig
from scalping.domain.models import RejectionReason, Side, SignalCandidate, StrategyEvaluation


@dataclass(frozen=True)
class MarketSnapshot:
    """Precomputed indicator values for one symbol at evaluation time.

    Deliberately holds plain floats, not indicator objects — indicator state lives
    in `scalping.indicators.incremental` (P2); the live pipeline (P6/P7) reads
    `.value` off those and builds one of these per evaluation.
    """

    symbol: str
    ema_fast_1m: float
    ema_slow_1m: float
    ema_fast_5m: float
    ema_slow_5m: float
    atr14_1m: float
    completed_close: float
    last_bar_high: float
    last_bar_low: float
    completed_quote_volume: float
    volume_median_30: float
    spread_bps: float
    seconds_to_next_funding: float
    btc_strength: float | None = None


@dataclass(frozen=True)
class MarketQualityFlags:
    """Cross-cutting checks owned by market_data validation / risk engine, not by
    CAEMS itself — passed in so the engine can still report the right rejection
    reason without importing those modules (keeps the strategy -> risk boundary
    one-directional).
    """

    kill_switch_engaged: bool = False
    symbol_disabled: bool = False
    shorts_enabled: bool = True
    stale_market_data: bool = False
    invalid_book: bool = False
    liquidity_too_low: bool = False


@dataclass(frozen=True)
class RiskCostDecision:
    """Risk gate (condition 11) and cost/edge gate (condition 12) outcomes, computed
    upstream by the risk engine (P4) and cost model (P5)."""

    risk_approved: bool
    risk_rejection: RejectionReason | None = None  # RISK_LIMIT or DRAW_DOWN_LIMIT
    cost_gate_passed: bool = True
    edge_sufficient: bool = True


def _stop_distance(snapshot: MarketSnapshot, config: EffectiveConfig) -> float:
    execution_floor = (
        3 * (snapshot.spread_bps / 10_000 * snapshot.completed_close)
        + 2 * config.exits.slippage_buffer
    )
    atr_stop = snapshot.atr14_1m
    return max(atr_stop, execution_floor)


def _reject(
    symbol: str, side: Side, evaluated_at: datetime, strength: float, config_hash: str,
    reason: RejectionReason,
) -> StrategyEvaluation:
    return StrategyEvaluation(
        symbol=symbol, side=side, evaluated_at=evaluated_at, strength=strength,
        config_hash=config_hash, accepted=False, rejection_reason=reason,
    )


def evaluate(
    *,
    side: Side,
    snapshot: MarketSnapshot,
    config: EffectiveConfig,
    frozen: FrozenParams,
    config_hash: str,
    evaluated_at: datetime,
    flags: MarketQualityFlags,
    risk_cost: RiskCostDecision,
) -> tuple[StrategyEvaluation, SignalCandidate | None]:
    """Evaluate one symbol/side under CAEMS v2. Returns (evaluation, signal) where
    `signal` is None unless every condition passed.
    """
    s = snapshot
    g = config.gates
    is_long = side is Side.LONG

    strength = (s.ema_fast_1m - s.ema_slow_1m) / s.atr14_1m
    if not is_long:
        strength = -strength  # symmetric: shorts want negative-going strength positive-signed

    def reject(reason: RejectionReason) -> tuple[StrategyEvaluation, None]:
        return (
            _reject(s.symbol, side, evaluated_at, strength, config_hash, reason),
            None,
        )

    # -- cross-cutting gates (market_data / risk engine owned) --------------------
    if flags.kill_switch_engaged:
        return reject(RejectionReason.KILL_SWITCH)
    if flags.symbol_disabled:
        return reject(RejectionReason.SYMBOL_DISABLED)
    if not is_long and not flags.shorts_enabled:
        return reject(RejectionReason.SHORTS_DISABLED)
    if flags.stale_market_data:
        return reject(RejectionReason.STALE_MARKET_DATA)
    if flags.invalid_book:
        return reject(RejectionReason.INVALID_BOOK)

    # -- 1. regime: 5m EMA stack agreement --
    regime_ok = s.ema_fast_5m > s.ema_slow_5m if is_long else s.ema_fast_5m < s.ema_slow_5m
    if not regime_ok:
        return reject(RejectionReason.NO_5M_TREND)

    # -- 2. momentum: 1m EMA stack agreement --
    momentum_ok = s.ema_fast_1m > s.ema_slow_1m if is_long else s.ema_fast_1m < s.ema_slow_1m
    if not momentum_ok:
        return reject(RejectionReason.NO_5M_TREND)

    # -- 3. deadband --
    if strength < g.strength_min:
        return reject(RejectionReason.DEAD_BAND_TOO_SMALL)

    # -- 4. strength cap --
    if strength > g.strength_max:
        return reject(RejectionReason.STRENGTH_TOO_EXTREME)

    # -- 5. confirmation --
    confirm_ok = (
        s.completed_close > s.ema_fast_1m if is_long else s.completed_close < s.ema_fast_1m
    )
    if not confirm_ok:
        return reject(RejectionReason.PRICE_CONFIRMATION_FAILED)

    # -- 6. entry location --
    max_extension = g.entry_max_atr * s.atr14_1m
    if is_long:
        extended = s.completed_close > s.ema_fast_1m + max_extension
    else:
        extended = s.completed_close < s.ema_fast_1m - max_extension
    if extended:
        return reject(RejectionReason.ENTRY_TOO_EXTENDED)

    # -- 7. volume --
    if s.completed_quote_volume < g.rvol_min * s.volume_median_30:
        return reject(RejectionReason.LOW_VOLUME)
    if flags.liquidity_too_low:
        return reject(RejectionReason.LIQUIDITY_TOO_LOW)

    # -- 8. candle quality --
    last_bar_range = s.last_bar_high - s.last_bar_low
    if last_bar_range > g.bar_range_max_atr * s.atr14_1m:
        return reject(RejectionReason.BAR_RANGE_ABNORMAL)

    # -- 9. funding proximity --
    if abs(s.seconds_to_next_funding) < g.funding_blackout_s:
        return reject(RejectionReason.FUNDING_BLACKOUT)

    # -- 10. spread --
    if s.spread_bps > g.spread_max_bps:
        return reject(RejectionReason.SPREAD_TOO_WIDE)

    # -- reserved: BTC veto (off by default; multi-symbol phase) --
    if g.btc_veto_enabled and s.btc_strength is not None:
        veto = (
            s.btc_strength <= -g.btc_veto_threshold
            if is_long
            else s.btc_strength >= g.btc_veto_threshold
        )
        if veto:
            return reject(RejectionReason.BTC_REGIME_VETO)

    # -- 11. risk gate --
    if not risk_cost.risk_approved:
        return reject(risk_cost.risk_rejection or RejectionReason.RISK_LIMIT)

    # -- 12. cost / edge gate --
    if not risk_cost.cost_gate_passed:
        return reject(RejectionReason.COST_TOO_HIGH)
    if not risk_cost.edge_sufficient:
        return reject(RejectionReason.EXPECTED_EDGE_TOO_LOW)

    # -- accepted: build the signal --
    stop_distance = _stop_distance(s, config)
    entry = s.completed_close
    if is_long:
        stop = entry - stop_distance
        take_profit = entry + frozen.take_profit_r * stop_distance
    else:
        stop = entry + stop_distance
        take_profit = entry - frozen.take_profit_r * stop_distance

    signal = SignalCandidate(
        symbol=s.symbol, side=side, strategy_version=frozen.strategy_version,
        signal_time=evaluated_at, entry_reference=entry, stop=stop, take_profit=take_profit,
        strength=strength, config_hash=config_hash,
    )
    evaluation = StrategyEvaluation(
        symbol=s.symbol, side=side, evaluated_at=evaluated_at, strength=strength,
        config_hash=config_hash, accepted=True,
    )
    return evaluation, signal
