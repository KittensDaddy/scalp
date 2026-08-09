"""Shared helpers for microstructure strategies (bookTicker + 1m candle proxies)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from scalping.config.settings import EffectiveConfig
from scalping.domain.models import (
    Candle,
    RejectionReason,
    Side,
    SignalCandidate,
    StrategyEvaluation,
)
from scalping.market_data.registry import SymbolState
from scalping.strategies.caems.engine import MarketQualityFlags, MarketSnapshot, RiskCostDecision


def robust_z(values: Sequence[float], current: float | None = None) -> float | None:
    """Median/MAD z-score. `current` defaults to last value."""
    if len(values) < 8:
        return None
    xs = list(values)
    x = xs[-1] if current is None else current
    ordered = sorted(xs)
    mid = len(ordered) // 2
    med = ordered[mid] if len(ordered) % 2 else 0.5 * (ordered[mid - 1] + ordered[mid])
    abs_dev = sorted(abs(v - med) for v in xs)
    mad = abs_dev[mid] if len(abs_dev) % 2 else 0.5 * (abs_dev[mid - 1] + abs_dev[mid])
    scale = 1.4826 * mad
    if scale <= 1e-18:
        return None
    return (x - med) / scale


def beta_residual_z(
    dep: Sequence[float], indep: Sequence[float], *, min_bars: int = 40
) -> float | None:
    n = min(len(dep), len(indep))
    if n < min_bars:
        return None
    a = list(dep)[-n:]
    b = list(indep)[-n:]
    mean_a = sum(a) / n
    mean_b = sum(b) / n
    var_b = sum((x - mean_b) ** 2 for x in b) / n
    if var_b <= 1e-18:
        return None
    cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b, strict=True)) / n
    beta = cov / var_b
    residuals = [x - beta * y for x, y in zip(a, b, strict=True)]
    return robust_z(residuals)


def returns_from_closes(closes: Sequence[float]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        if prev <= 0:
            continue
        out.append((closes[i] - prev) / prev)
    return out


def candle_closes(candles: Sequence[Candle]) -> list[float]:
    return [c.close for c in candles]


def reject(
    *,
    symbol: str,
    side: Side,
    evaluated_at: datetime,
    config_hash: str,
    reason: RejectionReason,
    strength: float = 0.0,
) -> tuple[StrategyEvaluation, None]:
    return (
        StrategyEvaluation(
            symbol=symbol,
            side=side,
            evaluated_at=evaluated_at,
            strength=strength,
            config_hash=config_hash,
            accepted=False,
            rejection_reason=reason,
        ),
        None,
    )


def common_gates(
    *,
    side: Side,
    snapshot: MarketSnapshot,
    config: EffectiveConfig,
    flags: MarketQualityFlags,
    risk_cost: RiskCostDecision,
    respect_caems_disable: bool = False,
) -> RejectionReason | None:
    """Shared hard gates. Microstructure ignores CAEMS observe_only by default."""
    if flags.kill_switch_engaged:
        return RejectionReason.KILL_SWITCH
    if respect_caems_disable and (
        flags.symbol_disabled or config.symbol_meta.disabled
    ):
        return RejectionReason.SYMBOL_DISABLED
    if flags.stale_market_data:
        return RejectionReason.STALE_MARKET_DATA
    if flags.invalid_book:
        return RejectionReason.INVALID_BOOK
    if side is Side.SHORT and (
        not flags.shorts_enabled or not config.symbol_meta.shorts_enabled
    ):
        return RejectionReason.SHORTS_DISABLED
    if snapshot.spread_bps > max(config.gates.spread_max_bps * 1.5, 8.0):
        return RejectionReason.SPREAD_TOO_WIDE
    if not risk_cost.risk_approved:
        return risk_cost.risk_rejection or RejectionReason.RISK_LIMIT
    return None


def make_signal_at(
    *,
    strategy_id: str,
    symbol: str,
    side: Side,
    entry: float,
    evaluated_at: datetime,
    config_hash: str,
    strength: float,
    stop_dist: float,
    tp_r: float,
) -> tuple[StrategyEvaluation, SignalCandidate]:
    stop_dist = max(stop_dist, entry * 0.0005)
    if side is Side.LONG:
        stop = entry - stop_dist
        tp = entry + tp_r * stop_dist
    else:
        stop = entry + stop_dist
        tp = entry - tp_r * stop_dist
    signal = SignalCandidate(
        symbol=symbol,
        side=side,
        strategy_version=strategy_id,
        signal_time=evaluated_at,
        entry_reference=entry,
        stop=stop,
        take_profit=tp,
        strength=strength,
        config_hash=config_hash,
    )
    evaluation = StrategyEvaluation(
        symbol=symbol,
        side=side,
        evaluated_at=evaluated_at,
        strength=strength,
        config_hash=config_hash,
        accepted=True,
    )
    return evaluation, signal


def entry_price(state: SymbolState, snapshot: MarketSnapshot) -> float:
    bt = state.last_book_ticker
    if bt is not None and bt.mid > 0:
        return bt.mid
    return snapshot.completed_close
