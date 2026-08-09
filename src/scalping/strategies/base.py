"""Strategy plugin protocol for multi-strategy evaluation."""

from __future__ import annotations

from typing import Protocol

from scalping.config.frozen import FrozenParams
from scalping.config.settings import EffectiveConfig
from scalping.domain.models import Side, SignalCandidate, StrategyEvaluation
from scalping.market_data.registry import SymbolState
from scalping.strategies.caems.engine import MarketQualityFlags, MarketSnapshot, RiskCostDecision


class StrategyPlugin(Protocol):
    strategy_id: str
    strategy_version: str

    def accepts_class(self, symbol_class: str) -> bool:
        """Whether this plugin should evaluate symbols of this CAEMS class."""
        ...

    def evaluate(
        self,
        *,
        side: Side,
        snapshot: MarketSnapshot,
        state: SymbolState,
        config: EffectiveConfig,
        frozen: FrozenParams,
        config_hash: str,
        evaluated_at: object,
        flags: MarketQualityFlags,
        risk_cost: RiskCostDecision,
        symbol_class: str,
        btc_snapshot: MarketSnapshot | None = None,
    ) -> tuple[StrategyEvaluation, SignalCandidate | None]: ...
