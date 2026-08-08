"""Developing Setups engine — SCANNER_DASHBOARD_PLAN.md §S7: "near-trigger detection
(score within Δ of threshold), missing-condition list, conditional projections".

A developing setup is a rejected symbol/side whose score is close enough to the
actionable threshold to be worth watching. `detect_developing_setup` is pure (no
network, no wall-clock reads inside — timestamp passed in) so it replays
deterministically, matching the S3 scoring module's contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from scalping.domain.models import Side
from scalping.strategies.caems.diagnostics import ConditionCheck


@dataclass(frozen=True)
class NearTriggerConfig:
    score_threshold: float = 70.0
    score_delta: float = 20.0
    max_missing_conditions: int = 3


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
    """Returns a DevelopingSetup when a rejected row's score is within `score_delta`
    of `score_threshold` and few enough conditions remain unmet, else None. Accepted
    rows are never "developing" — they've already triggered.
    """
    if accepted:
        return None
    if score < config.score_threshold - config.score_delta:
        return None

    failing = [c for c in conditions if not c.passed]
    if not failing or len(failing) > config.max_missing_conditions:
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
    """Batch form of `detect_developing_setup` over (symbol, side, score, accepted,
    conditions) tuples, ranked by score descending."""
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
    return sorted(setups, key=lambda s: s.score, reverse=True)


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
