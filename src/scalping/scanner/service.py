"""ScannerService — SCANNER_DASHBOARD_PLAN.md §C: "ScannerService (rank, diff,
publish)". Read-only over the pipeline; it never places orders (§C: "Scanner is
read-only over the pipeline"). Owns the ranked view and the seq-numbered delta
stream that S5's `/stream/scanner` WS endpoint will publish from.
"""

from __future__ import annotations

from dataclasses import dataclass

from scalping.domain.models import RejectionReason, Side
from scalping.scoring.score import ScoreBreakdown


@dataclass(frozen=True)
class ScannerRow:
    symbol: str
    side: Side
    score: float
    accepted: bool
    rejection_reason: RejectionReason | None
    breakdown: ScoreBreakdown | None
    strategy: str = "caems_v2"
    preset: str | None = None


@dataclass(frozen=True)
class ScannerSnapshot:
    seq: int
    rows: list[ScannerRow]


@dataclass(frozen=True)
class ScannerDelta:
    seq: int
    upserts: list[ScannerRow]
    removals: list[str]


class ScannerService:
    def __init__(self) -> None:
        self._rows: dict[str, ScannerRow] = {}
        self._seq = 0

    def publish(self, new_rows: list[ScannerRow]) -> ScannerDelta:
        """One row per symbol (ranking is over symbols, not symbol+side pairs —
        a symbol contributes whichever side row was passed for it)."""
        new_by_symbol = {r.symbol: r for r in new_rows}
        upserts = [r for sym, r in new_by_symbol.items() if self._rows.get(sym) != r]
        removals = [sym for sym in self._rows if sym not in new_by_symbol]
        self._rows = new_by_symbol
        self._seq += 1
        return ScannerDelta(seq=self._seq, upserts=upserts, removals=removals)

    def snapshot(self) -> ScannerSnapshot:
        ranked = sorted(self._rows.values(), key=lambda r: r.score, reverse=True)
        return ScannerSnapshot(seq=self._seq, rows=ranked)

    def row(self, symbol: str) -> ScannerRow | None:
        return self._rows.get(symbol)
