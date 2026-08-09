"""Replay → UI feed bridge — SCANNER_DASHBOARD_PLAN.md §S12.

Drives ScannerService / DevelopingSetupsService / ActiveTradeService from a
deterministic evaluation pass so the WS payloads are byte-identical across
replays of the same input (zero look-ahead: only data ≤ t is used).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from scalping.api.routers.developing import serialize_developing_setup
from scalping.api.routers.positions import serialize_active_trade
from scalping.domain.models import Position, Side
from scalping.monitoring.active_trades import ActiveTradeService
from scalping.scanner.developing import DevelopingSetup, DevelopingSetupsService
from scalping.scanner.service import ScannerRow, ScannerService
from scalping.scoring.score import ScoreBreakdown


@dataclass(frozen=True)
class UiFeedFrame:
    """One UI-visible snapshot at time `ts` — used for determinism checks."""

    ts: datetime
    scanner: dict[str, Any]
    developing: dict[str, Any]
    positions: dict[str, Any]

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            {
                "ts": self.ts.isoformat(),
                "scanner": self.scanner,
                "developing": self.developing,
                "positions": self.positions,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


class UiFeedRecorder:
    """Publishes into the three live services and records canonical frames."""

    def __init__(
        self,
        scanner: ScannerService | None = None,
        developing: DevelopingSetupsService | None = None,
        active_trades: ActiveTradeService | None = None,
    ) -> None:
        self.scanner = scanner or ScannerService()
        self.developing = developing or DevelopingSetupsService()
        self.active_trades = active_trades or ActiveTradeService()
        self.frames: list[UiFeedFrame] = []

    def publish_scanner(self, rows: list[ScannerRow], *, ts: datetime) -> UiFeedFrame:
        self.scanner.publish(rows)
        return self._record(ts)

    def publish_developing(self, setups: list[DevelopingSetup], *, ts: datetime) -> UiFeedFrame:
        self.developing.publish(setups)
        return self._record(ts)

    def open_position(
        self,
        *,
        trade_id: str,
        position: Position,
        ts: datetime,
        score: float | None = None,
    ) -> UiFeedFrame:
        self.active_trades.open_trade(
            trade_id=trade_id, position=position, score=score, ts=ts
        )
        return self._record(ts)

    def _record(self, ts: datetime) -> UiFeedFrame:
        snap_s = self.scanner.snapshot()
        snap_d = self.developing.snapshot()
        snap_p = self.active_trades.snapshot()
        frame = UiFeedFrame(
            ts=ts,
            scanner={
                "seq": snap_s.seq,
                "rows": [
                    {
                        "symbol": r.symbol,
                        "side": r.side.value,
                        "score": r.score,
                        "accepted": r.accepted,
                        "rejection_reason": (
                            r.rejection_reason.value if r.rejection_reason else None
                        ),
                    }
                    for r in snap_s.rows
                ],
            },
            developing={
                "seq": snap_d.seq,
                "setups": [serialize_developing_setup(s) for s in snap_d.setups],
            },
            positions={
                "seq": snap_p.seq,
                "positions": [serialize_active_trade(t) for t in snap_p.positions],
            },
        )
        self.frames.append(frame)
        return frame


def assert_feeds_identical(a: list[UiFeedFrame], b: list[UiFeedFrame]) -> None:
    if len(a) != len(b):
        raise AssertionError(f"frame count differs: {len(a)} vs {len(b)}")
    for i, (fa, fb) in enumerate(zip(a, b, strict=True)):
        if fa.canonical_bytes() != fb.canonical_bytes():
            raise AssertionError(f"frame {i} diverged at ts={fa.ts.isoformat()}")


def make_scanner_row(
    symbol: str,
    side: Side,
    score: float,
    *,
    accepted: bool = False,
    ts: datetime | None = None,
) -> ScannerRow:
    evaluated_at = ts or datetime(2026, 8, 9, tzinfo=None)
    return ScannerRow(
        symbol=symbol,
        side=side,
        score=score,
        accepted=accepted,
        rejection_reason=None,
        breakdown=ScoreBreakdown(
            total=score, components={"stub": score}, stale=False, evaluated_at=evaluated_at
        ),
    )
