from __future__ import annotations

from scalping.domain.models import Side
from scalping.scanner.service import ScannerRow, ScannerService


def _row(symbol: str, score: float) -> ScannerRow:
    return ScannerRow(symbol=symbol, side=Side.LONG, score=score, accepted=True,
                       rejection_reason=None, breakdown=None)


def test_first_publish_all_upserts_no_removals():
    svc = ScannerService()
    delta = svc.publish([_row("BTCUSDT", 80.0), _row("ETHUSDT", 60.0)])
    assert delta.seq == 1
    assert {r.symbol for r in delta.upserts} == {"BTCUSDT", "ETHUSDT"}
    assert delta.removals == []


def test_second_publish_only_diffs():
    svc = ScannerService()
    svc.publish([_row("BTCUSDT", 80.0), _row("ETHUSDT", 60.0)])
    delta = svc.publish([_row("BTCUSDT", 85.0), _row("ETHUSDT", 60.0)])  # ETH unchanged
    assert delta.seq == 2
    assert [r.symbol for r in delta.upserts] == ["BTCUSDT"]
    assert delta.removals == []


def test_symbol_dropped_from_new_rows_is_a_removal():
    svc = ScannerService()
    svc.publish([_row("BTCUSDT", 80.0), _row("ETHUSDT", 60.0)])
    delta = svc.publish([_row("BTCUSDT", 80.0)])
    assert delta.removals == ["ETHUSDT"]


def test_snapshot_ranked_by_score_descending():
    svc = ScannerService()
    svc.publish([_row("LOW", 10.0), _row("HIGH", 90.0), _row("MID", 50.0)])
    snapshot = svc.snapshot()
    assert [r.symbol for r in snapshot.rows] == ["HIGH", "MID", "LOW"]
    assert snapshot.seq == 1


def test_row_lookup_by_symbol():
    svc = ScannerService()
    svc.publish([_row("BTCUSDT", 80.0)])
    assert svc.row("BTCUSDT").score == 80.0
    assert svc.row("NOPE") is None


def test_seq_increments_every_publish():
    svc = ScannerService()
    svc.publish([_row("A", 1.0)])
    svc.publish([_row("A", 1.0)])
    svc.publish([_row("A", 1.0)])
    assert svc.snapshot().seq == 3
