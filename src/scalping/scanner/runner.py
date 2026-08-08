"""StrategyRunner — SCANNER_DASHBOARD_PLAN.md §C: "StrategyRunner -> Strategy
plugins (CAEMS...) -> SignalCandidate". Orchestrates one evaluation pass across
symbols: cooldown check -> CAEMS evaluate (per side) -> feature/score computation
-> best-side row per symbol -> publish to `ScannerService`.

Per-symbol market state (`SymbolState`, `MarketSnapshot`, feature inputs) is
supplied by the caller via `SymbolEvalContext` rather than fetched here — keeping
this module network-free and directly testable, consistent with every other
orchestration layer in this codebase (`execution/`, `market_data/manager.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from scalping.config.frozen import FrozenParams
from scalping.config.settings import EffectiveConfig
from scalping.domain.models import RejectionReason, Side
from scalping.market_data.registry import SymbolState
from scalping.scanner.cooldowns import CooldownManager
from scalping.scanner.developing import (
    DevelopingSetupsService,
    NearTriggerConfig,
    detect_developing_setups,
)
from scalping.scanner.service import ScannerDelta, ScannerRow, ScannerService
from scalping.scoring.features import FeatureRawInputs, compute_features
from scalping.scoring.score import ScoreWeights, score
from scalping.strategies.caems.diagnostics import evaluate_conditions
from scalping.strategies.caems.engine import MarketQualityFlags, MarketSnapshot, RiskCostDecision
from scalping.strategies.caems.plugin import CAEMSStrategy


@dataclass(frozen=True)
class SymbolEvalContext:
    symbol: str
    symbol_class: str
    state: SymbolState
    snapshot: MarketSnapshot
    feature_raw_by_side: dict[Side, FeatureRawInputs]
    flags: MarketQualityFlags
    risk_cost_by_side: dict[Side, RiskCostDecision]


class StrategyRunner:
    def __init__(
        self,
        strategy: CAEMSStrategy | None = None,
        cooldowns: CooldownManager | None = None,
        scanner: ScannerService | None = None,
        weights: ScoreWeights | None = None,
        developing: DevelopingSetupsService | None = None,
        near_trigger: NearTriggerConfig | None = None,
    ) -> None:
        self.strategy = strategy or CAEMSStrategy()
        self.cooldowns = cooldowns or CooldownManager()
        self.scanner = scanner or ScannerService()
        self.weights = weights or ScoreWeights()
        self.developing = developing or DevelopingSetupsService()
        self.near_trigger = near_trigger or NearTriggerConfig()

    def run_once(
        self,
        contexts: list[SymbolEvalContext],
        *,
        config: EffectiveConfig,
        frozen: FrozenParams,
        config_hash: str,
        evaluated_at: datetime,
        sides: tuple[Side, ...] = (Side.LONG, Side.SHORT),
    ) -> ScannerDelta:
        rows: list[ScannerRow] = []
        candidates: list[tuple[str, Side, float, bool, list]] = []
        for ctx in contexts:
            if self.cooldowns.is_active("symbol", ctx.symbol, evaluated_at):
                rows.append(
                    ScannerRow(
                        symbol=ctx.symbol, side=Side.LONG, score=0.0, accepted=False,
                        rejection_reason=RejectionReason.SYMBOL_DISABLED, breakdown=None,
                    )
                )
                continue

            best_row: ScannerRow | None = None
            for side in sides:
                evaluation, _signal = self.strategy.evaluate(
                    side=side, snapshot=ctx.snapshot, config=config, frozen=frozen,
                    config_hash=config_hash, evaluated_at=evaluated_at, flags=ctx.flags,
                    risk_cost=ctx.risk_cost_by_side[side],
                )
                raw = ctx.feature_raw_by_side[side]
                inputs = compute_features(ctx.state, raw)
                breakdown = score(inputs, self.weights)
                row = ScannerRow(
                    symbol=ctx.symbol, side=side, score=breakdown.total,
                    accepted=evaluation.accepted, rejection_reason=evaluation.rejection_reason,
                    breakdown=breakdown,
                )
                if best_row is None or row.score > best_row.score:
                    best_row = row

                conditions = evaluate_conditions(
                    side=side, snapshot=ctx.snapshot, config=config, frozen=frozen,
                )
                candidates.append(
                    (ctx.symbol, side, breakdown.total, evaluation.accepted, conditions)
                )
            assert best_row is not None
            rows.append(best_row)

        setups = detect_developing_setups(candidates, self.near_trigger, evaluated_at)
        self.developing.publish(setups)

        return self.scanner.publish(rows)
