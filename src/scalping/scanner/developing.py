"""Developing Setups engine — SCANNER_DASHBOARD_PLAN.md §S7: "near-trigger detection
(score within Δ of threshold), missing-condition list, conditional projections".

A developing setup is a rejected symbol/side whose score is close enough to the
actionable threshold to be worth watching — or which already passes most CAEMS
gates with only a few missing. `detect_developing_setup` is pure (timestamp
passed in) so it replays deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from scalping.domain.models import Side
from scalping.strategies.caems.diagnostics import ConditionCheck


@dataclass(frozen=True)
class NearTriggerConfig:
    score_threshold: float = 55.0
    score_delta: float = 15.0  # score path: >= 40 with defaults
    max_missing_conditions: int = 5
    # Alternate path: enough gates already green even if score is still low.
    min_passed_conditions: int = 5
    # Hard floor: Developing tab only lists setups scoring at least this.
    min_score: float = 40.0


@dataclass(frozen=True)
class DevelopingSetup:
    symbol: str
    side: Side
    score: float
    missing_conditions: list[str]
    projections: dict[str, str]
    detected_at: datetime


def detect_developing_setup(
    *,
    symbol: str,
    side: Side,
    score: float,
    accepted: bool,
    conditions: list[ConditionCheck],
    config: NearTriggerConfig,
    evaluated_at: datetime,
) -> DevelopingSetup | None:
    """Returns a DevelopingSetup when a rejected row is near actionable.

    Accepted rows are never "developing" — they've already triggered.
    """
    if accepted:
        return None
    if score < config.min_score:
        return None

    failing = [c for c in conditions if not c.passed]
    if not failing or len(failing) > config.max_missing_conditions:
        return None

    passed_n = sum(1 for c in conditions if c.passed)
    score_ok = score >= (config.score_threshold - config.score_delta)
    gates_ok = passed_n >= config.min_passed_conditions
    if not (score_ok or gates_ok):
        return None

    return DevelopingSetup(
        symbol=symbol,
        side=side,
        score=score,
        missing_conditions=[c.name for c in failing],
        projections={c.name: c.detail for c in failing},
        detected_at=evaluated_at,
    )


def detect_developing_setups(
    candidates: list[tuple[str, Side, float, bool, list[ConditionCheck]]],
    config: NearTriggerConfig,
    evaluated_at: datetime,
) -> list[DevelopingSetup]:
    """Batch form; one setup per symbol (best score), ranked descending."""
    setups = [
        setup
        for symbol, side, score, accepted, conditions in candidates
        if (
            setup := detect_developing_setup(
                symbol=symbol, side=side, score=score, accepted=accepted,
                conditions=conditions, config=config, evaluated_at=evaluated_at,
            )
        )
        is not None
    ]
    best: dict[str, DevelopingSetup] = {}
    for s in setups:
        prev = best.get(s.symbol)
        if prev is None or s.score > prev.score:
            best[s.symbol] = s
    return sorted(best.values(), key=lambda s: s.score, reverse=True)


@dataclass(frozen=True)
class DevelopingSetupsSnapshot:
    seq: int
    setups: list[DevelopingSetup]


class DevelopingSetupsService:
    """Read-only holder for the latest developing-setups pass, mirroring
    `ScannerService`'s seq-numbered publish/snapshot shape so S7's own tab can reuse
    the same resnapshot-on-gap client pattern as the main scanner."""

    def __init__(self) -> None:
        self._setups: list[DevelopingSetup] = []
        self._seq = 0

    def publish(self, setups: list[DevelopingSetup]) -> DevelopingSetupsSnapshot:
        self._setups = setups
        self._seq += 1
        return self.snapshot()

    def snapshot(self) -> DevelopingSetupsSnapshot:
        return DevelopingSetupsSnapshot(seq=self._seq, setups=self._setups)
