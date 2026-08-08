"""CAEMS as a `Strategy` plugin — SCANNER_DASHBOARD_PLAN.md §A: "First
Strategy.evaluate() plugin; wrap, don't modify rules." This is a pure delegation
to `strategies.caems.engine.evaluate`; no rule logic lives here.
"""

from __future__ import annotations

from datetime import datetime

from scalping.config.frozen import FrozenParams
from scalping.config.settings import EffectiveConfig
from scalping.domain.models import Side, SignalCandidate, StrategyEvaluation
from scalping.strategies.caems.engine import (
    MarketQualityFlags,
    MarketSnapshot,
    RiskCostDecision,
    evaluate,
)


class CAEMSStrategy:
    strategy_version = "caems_v2"

    def evaluate(
        self,
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
        return evaluate(
            side=side, snapshot=snapshot, config=config, frozen=frozen,
            config_hash=config_hash, evaluated_at=evaluated_at, flags=flags, risk_cost=risk_cost,
        )
