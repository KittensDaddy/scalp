"""S9 journal enrichment + analytics."""

from __future__ import annotations

from datetime import UTC, datetime

from scalping.accounting.journal import (
    CostBreakdown,
    build_auto_notes,
    enrich_trade,
    group_analytics,
)

NOW = datetime(2026, 8, 9, 14, 30, tzinfo=UTC)


def test_auto_notes_flag_deep_mae_recovery_and_time_stop():
    notes = build_auto_notes(
        r_multiple=0.8, mae_r=1.1, mfe_r=0.9, exit_reason="TIME_STOP",
        protected=True, breakeven_moved=True,
        score_at_entry=90.0, score_at_exit=70.0,
    )
    assert any("deep adverse" in n for n in notes)
    assert any("breakeven" in n for n in notes)
    assert any("score decayed" in n for n in notes)
    assert any("time stop" in n for n in notes)


def test_enrich_trade_hour_and_cost():
    cost = CostBreakdown(fees_r=0.02, spread_r=0.01, slippage_r=0.0)
    j = enrich_trade(
        trade_id="t1", symbol="BTCUSDT", side="LONG", r_multiple=1.35,
        mae_r=0.2, mfe_r=1.4, exit_reason="TAKE_PROFIT",
        opened_at=NOW, closed_at=NOW, strategy_version="caems_v2", cost=cost,
        score_at_exit=85.0, regime="trend_up", session="london",
    )
    assert j.hour_utc == 14
    assert j.cost_breakdown.total_r == 0.03
    assert j.regime == "trend_up"


def test_group_analytics_by_symbol():
    trades = [
        {"symbol": "BTCUSDT", "r_multiple": 1.0, "mae_r": 0.2, "mfe_r": 1.1,
         "strategy_version": "caems_v2", "closed_at": NOW},
        {"symbol": "BTCUSDT", "r_multiple": -1.0, "mae_r": 1.0, "mfe_r": 0.1,
         "strategy_version": "caems_v2", "closed_at": NOW},
        {"symbol": "ETHUSDT", "r_multiple": 0.5, "mae_r": 0.1, "mfe_r": 0.6,
         "strategy_version": "caems_v2", "closed_at": NOW},
    ]
    groups = group_analytics(trades, group_by="symbol")
    by_key = {g.key: g for g in groups}
    assert by_key["BTCUSDT"].n == 2
    assert by_key["BTCUSDT"].sum_r == 0.0
    assert by_key["ETHUSDT"].n == 1
    assert by_key["ETHUSDT"].avg_r == 0.5
