from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scalping.domain.models import (
    BookTicker,
    RejectionReason,
    Side,
    StrategyEvaluation,
)


def test_book_ticker_spread_bps():
    bt = BookTicker(
        symbol="BTCUSDT",
        bid_price=100.0,
        bid_qty=1,
        ask_price=100.1,
        ask_qty=1,
        event_time=datetime.now(UTC),
    )
    assert bt.mid == pytest.approx(100.05)
    assert bt.spread_bps == pytest.approx(9.995, rel=1e-3)


def test_evaluation_accepted_forbids_rejection_reason():
    with pytest.raises(ValueError, match="must not carry"):
        StrategyEvaluation(
            symbol="BTCUSDT",
            side=Side.LONG,
            evaluated_at=datetime.now(UTC),
            strength=0.5,
            config_hash="x",
            accepted=True,
            rejection_reason=RejectionReason.LOW_VOLUME,
        )


def test_evaluation_rejected_requires_reason():
    with pytest.raises(ValueError, match="must carry"):
        StrategyEvaluation(
            symbol="BTCUSDT",
            side=Side.LONG,
            evaluated_at=datetime.now(UTC),
            strength=0.5,
            config_hash="x",
            accepted=False,
        )


def test_evaluation_valid_rejected():
    ev = StrategyEvaluation(
        symbol="BTCUSDT",
        side=Side.LONG,
        evaluated_at=datetime.now(UTC),
        strength=0.1,
        config_hash="x",
        accepted=False,
        rejection_reason=RejectionReason.DEAD_BAND_TOO_SMALL,
    )
    assert ev.rejection_reason == RejectionReason.DEAD_BAND_TOO_SMALL


def test_all_20_rejection_reasons_present():
    expected = {
        "NO_5M_TREND", "DEAD_BAND_TOO_SMALL", "STRENGTH_TOO_EXTREME",
        "PRICE_CONFIRMATION_FAILED", "ENTRY_TOO_EXTENDED", "LOW_VOLUME",
        "BAR_RANGE_ABNORMAL", "FUNDING_BLACKOUT", "SPREAD_TOO_WIDE",
        "BTC_REGIME_VETO", "COST_TOO_HIGH", "EXPECTED_EDGE_TOO_LOW",
        "RISK_LIMIT", "DRAW_DOWN_LIMIT", "STALE_MARKET_DATA", "INVALID_BOOK",
        "SYMBOL_DISABLED", "LIQUIDITY_TOO_LOW", "KILL_SWITCH", "SHORTS_DISABLED",
    }
    assert {r.value for r in RejectionReason} == expected
    assert len(expected) == 20
