"""S12 replay-driven UI feed determinism."""

from __future__ import annotations

from datetime import UTC, datetime

from scalping.domain.models import Position, Side
from scalping.replay.ui_feed import (
    UiFeedRecorder,
    assert_feeds_identical,
    make_scanner_row,
)
from scalping.scanner.developing import DevelopingSetup

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def _drive(recorder: UiFeedRecorder) -> None:
    recorder.publish_scanner(
        [make_scanner_row("BTCUSDT", Side.LONG, 88.0, accepted=True, ts=NOW)],
        ts=NOW,
    )
    recorder.publish_developing(
        [
            DevelopingSetup(
                symbol="ETHUSDT", side=Side.LONG, score=55.0,
                missing_conditions=["volume"], projections={"volume": "low"},
                detected_at=NOW,
            )
        ],
        ts=NOW,
    )
    recorder.open_position(
        trade_id="t1",
        position=Position(
            symbol="BTCUSDT", side=Side.LONG, entry_price=100.0, quantity=1.0,
            stop_price=99.0, take_profit_price=101.35, opened_at=NOW,
        ),
        ts=NOW,
        score=88.0,
    )


def test_ui_feed_byte_identical_across_replays():
    a = UiFeedRecorder()
    b = UiFeedRecorder()
    _drive(a)
    _drive(b)
    assert_feeds_identical(a.frames, b.frames)
    assert len(a.frames) == 3
    assert a.frames[-1].positions["positions"][0]["symbol"] == "BTCUSDT"
