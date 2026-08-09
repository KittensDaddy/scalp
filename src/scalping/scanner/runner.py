"""StrategyRunner — multi-plugin evaluation (CAEMS + microstructure).

For each symbol, every enabled plugin that accepts the symbol class is evaluated.
Scanner publishes one row per symbol (best score across plugins). All accepted
signals are returned for the paper/live executor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from scalping.config.frozen import FrozenParams
from scalping.config.settings import EffectiveConfig
from scalping.domain.models import RejectionReason, Side, SignalCandidate
from scalping.market_data.registry import SymbolState
from scalping.scanner.cooldowns import CooldownManager
from scalping.scanner.developing import (
    DevelopingSetupsService,
    NearTriggerConfig,
    detect_developing_setups,
)
from scalping.scanner.service import ScannerRow, ScannerService
from scalping.scoring.features import FeatureRawInputs, compute_features
from scalping.scoring.score import ScoreWeights, score
from scalping.strategies.caems.diagnostics import evaluate_conditions
from scalping.strategies.caems.engine import MarketQualityFlags, MarketSnapshot, RiskCostDecision
from scalping.strategies.caems.plugin import CAEMSStrategy
from scalping.strategies.microstructure.plugins import all_microstructure_strategies


@dataclass(frozen=True)
class SymbolEvalContext:
    symbol: str
    symbol_class: str
    state: SymbolState
    snapshot: MarketSnapshot
    feature_raw_by_side: dict[Side, FeatureRawInputs]
    flags: MarketQualityFlags
    risk_cost_by_side: dict[Side, RiskCostDecision]
    config: EffectiveConfig | None = None
    config_hash: str | None = None
    preset: str | None = None


@dataclass(frozen=True)
class RunnerPassResult:
    delta: Any  # ScannerDelta
    signals: list[SignalCandidate]


@dataclass
class StrategyRunner:
    """Multi-plugin runner. Defaults to CAEMS + all microstructure strategies."""

    cooldowns: CooldownManager = field(default_factory=CooldownManager)
    scanner: ScannerService = field(default_factory=ScannerService)
    weights: ScoreWeights = field(default_factory=ScoreWeights)
    developing: DevelopingSetupsService = field(default_factory=DevelopingSetupsService)
    near_trigger: NearTriggerConfig = field(default_factory=NearTriggerConfig)
    strategies: list[Any] = field(default_factory=list)
    enabled_ids: set[str] | None = None
    # Back-compat alias used by older tests
    strategy: CAEMSStrategy | None = None

    def __post_init__(self) -> None:
        if self.strategy is not None and not self.strategies:
            self.strategies = [self.strategy]
        if not self.strategies:
            plugins: list[Any] = [CAEMSStrategy()]
            plugins.extend(all_microstructure_strategies())
            if self.enabled_ids is not None:
                plugins = [p for p in plugins if p.strategy_id in self.enabled_ids]
            self.strategies = plugins
        if self.strategy is None:
            for p in self.strategies:
                if getattr(p, "strategy_id", None) == "caems_v2":
                    self.strategy = p
                    break

    def run_once(
        self,
        contexts: list[SymbolEvalContext],
        *,
        config: EffectiveConfig | None = None,
        frozen: FrozenParams,
        config_hash: str | None = None,
        evaluated_at: datetime,
        sides: tuple[Side, ...] = (Side.LONG, Side.SHORT),
        btc_snapshot: MarketSnapshot | None = None,
    ) -> RunnerPassResult:
        rows: list[ScannerRow] = []
        signals: list[SignalCandidate] = []
        candidates: list[tuple[str, Side, float, bool, list]] = []

        if btc_snapshot is not None:
            for plugin in self.strategies:
                note = getattr(plugin, "note_btc_close", None)
                if callable(note):
                    note(btc_snapshot.completed_close)

        for ctx in contexts:
            cfg = ctx.config if hasattr(ctx, "config") and ctx.config is not None else config
            ch = ctx.config_hash if getattr(ctx, "config_hash", None) else config_hash
            assert cfg is not None and ch is not None

            # Global scope covers feed-wide pauses (API reconnect); symbol scope
            # covers post-trade timeouts. Either one holds the symbol out.
            if self.cooldowns.is_active(
                "global", "*", evaluated_at
            ) or self.cooldowns.is_active("symbol", ctx.symbol, evaluated_at):
                rows.append(
                    ScannerRow(
                        symbol=ctx.symbol, side=Side.LONG, score=0.0, accepted=False,
                        rejection_reason=RejectionReason.COOLDOWN, breakdown=None,
                        strategy="caems_v2", preset=ctx.preset,
                    )
                )
                continue

            best_row: ScannerRow | None = None

            for plugin in self.strategies:
                if not plugin.accepts_class(ctx.symbol_class):
                    continue
                for side in sides:
                    evaluation, signal = plugin.evaluate(
                        side=side,
                        snapshot=ctx.snapshot,
                        state=ctx.state,
                        config=cfg,
                        frozen=frozen,
                        config_hash=ch,
                        evaluated_at=evaluated_at,
                        flags=ctx.flags,
                        risk_cost=ctx.risk_cost_by_side[side],
                        symbol_class=ctx.symbol_class,
                        btc_snapshot=btc_snapshot,
                    )
                    raw = ctx.feature_raw_by_side[side]
                    inputs = compute_features(ctx.state, raw)
                    breakdown = score(inputs, self.weights)
                    row_score = breakdown.total
                    # Only boost accepted microstructure rows — rejected VSHOCK/etc.
                    # strength was flooding the scanner with fake "near trigger" 100s.
                    if (
                        evaluation.accepted
                        and evaluation.strength
                        and plugin.strategy_id != "caems_v2"
                    ):
                        row_score = max(
                            row_score, min(100.0, abs(evaluation.strength) * 25.0)
                        )
                    row = ScannerRow(
                        symbol=ctx.symbol,
                        side=side,
                        score=row_score,
                        accepted=evaluation.accepted,
                        rejection_reason=evaluation.rejection_reason,
                        breakdown=breakdown,
                        strategy=plugin.strategy_id,
                        preset=ctx.preset,
                    )
                    if best_row is None or row.score > best_row.score or (
                        row.accepted and not best_row.accepted
                    ):
                        best_row = row
                    if evaluation.accepted and signal is not None:
                        signals.append(signal)

                    if plugin.strategy_id == "caems_v2":
                        conditions = evaluate_conditions(
                            side=side, snapshot=ctx.snapshot, config=cfg, frozen=frozen,
                        )
                        # Developing always uses CAEMS score, not a rival plugin's.
                        candidates.append(
                            (
                                ctx.symbol,
                                side,
                                breakdown.total,
                                evaluation.accepted,
                                conditions,
                            )
                        )

            if best_row is None:
                best_row = ScannerRow(
                    symbol=ctx.symbol, side=Side.LONG, score=0.0, accepted=False,
                    rejection_reason=RejectionReason.DATA_UNAVAILABLE, breakdown=None,
                    strategy="none", preset=ctx.preset,
                )
            rows.append(best_row)

        setups = detect_developing_setups(candidates, self.near_trigger, evaluated_at)
        self.developing.publish(setups)
        return RunnerPassResult(delta=self.scanner.publish(rows), signals=signals)
