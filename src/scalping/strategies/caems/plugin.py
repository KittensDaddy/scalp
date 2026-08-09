"""CAEMS as a `Strategy` plugin — SCANNER_DASHBOARD_PLAN.md §A: "First
Strategy.evaluate() plugin; wrap, don't modify rules." This is a pure delegation
to `strategies.caems.engine.evaluate`; no rule logic lives here.
"""

from __future__ import annotations

from datetime import datetime

from scalping.config.frozen import FrozenParams
from scalping.config.settings import EffectiveConfig
from scalping.domain.models import RejectionReason, Side, SignalCandidate, StrategyEvaluation
from scalping.market_data.registry import SymbolState
from scalping.strategies.caems.engine import (
    MarketQualityFlags,
    MarketSnapshot,
    RiskCostDecision,
    evaluate,
)


class CAEMSStrategy:
    strategy_id = "caems_v2"
    strategy_version = "caems_v2"

    def accepts_class(self, symbol_class: str) -> bool:
        # CAEMS runs on every class; disabled/observe_only handled via config flags.
        return True

    def evaluate(
        self,
        *,
        side: Side,
        snapshot: MarketSnapshot,
        state: SymbolState,
        config: EffectiveConfig,
        frozen: FrozenParams,
        config_hash: str,
        evaluated_at: datetime,
        flags: MarketQualityFlags,
        risk_cost: RiskCostDecision,
        symbol_class: str,
        btc_snapshot: MarketSnapshot | None = None,
    ) -> tuple[StrategyEvaluation, SignalCandidate | None]:
        # Merge observe_only / disabled from symbol_meta into flags
        if config.symbol_meta.disabled:
            flags = MarketQualityFlags(
                kill_switch_engaged=flags.kill_switch_engaged,
                symbol_disabled=True,
                shorts_enabled=flags.shorts_enabled and config.symbol_meta.shorts_enabled,
                stale_market_data=flags.stale_market_data,
                invalid_book=flags.invalid_book,
                liquidity_too_low=flags.liquidity_too_low,
            )
        if config.symbol_meta.observe_only:
            return (
                StrategyEvaluation(
                    symbol=snapshot.symbol, side=side, evaluated_at=evaluated_at,
                    strength=0.0, config_hash=config_hash, accepted=False,
                    rejection_reason=RejectionReason.OBSERVE_ONLY,
                ),
                None,
            )
        shorts_ok = flags.shorts_enabled and config.symbol_meta.shorts_enabled
        if not shorts_ok:
            flags = MarketQualityFlags(
                kill_switch_engaged=flags.kill_switch_engaged,
                symbol_disabled=flags.symbol_disabled,
                shorts_enabled=False,
                stale_market_data=flags.stale_market_data,
                invalid_book=flags.invalid_book,
                liquidity_too_low=flags.liquidity_too_low,
            )
        return evaluate(
            side=side, snapshot=snapshot, config=config, frozen=frozen,
            config_hash=config_hash, evaluated_at=evaluated_at, flags=flags, risk_cost=risk_cost,
        )
