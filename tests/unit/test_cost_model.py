from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from scalping.config.settings import CostConfig
from scalping.costmodel.cost import (
    compute_round_trip_cost,
    cost_gate_passed,
    funding_cost_if_straddled,
)


def test_maker_entry_taker_exit_cost_breakdown():
    cfg = CostConfig(maker_fee_bps=2.0, taker_fee_bps=5.0, safety_buffer_bps=1.0)
    cost = compute_round_trip_cost(cost_cfg=cfg, spread_bps=1.5, is_maker_entry=True, exit_is_taker=True)
    assert cost.entry_fee_bps == 2.0
    assert cost.exit_fee_bps == 5.0
    assert cost.spread_cost_bps == 1.5
    assert cost.slippage_bps == 1.0
    assert cost.total_bps == pytest.approx(9.5)


def test_funding_added_to_total():
    cfg = CostConfig()
    cost = compute_round_trip_cost(cost_cfg=cfg, spread_bps=1.0, funding_bps=3.0)
    assert cost.funding_bps == 3.0
    assert cost.total_bps == pytest.approx(cfg.maker_fee_bps + cfg.taker_fee_bps + 1.0 + cfg.safety_buffer_bps + 3.0)


def test_cost_gate_passes_when_edge_exceeds_multiplier():
    cfg = CostConfig(maker_fee_bps=2.0, taker_fee_bps=5.0, safety_buffer_bps=1.0)
    cost = compute_round_trip_cost(cost_cfg=cfg, spread_bps=1.0)
    assert cost.total_bps == pytest.approx(9.0)
    assert cost_gate_passed(expected_gross_edge_bps=20.0, cost=cost, cost_edge_multiplier=1.5) is True
    assert cost_gate_passed(expected_gross_edge_bps=10.0, cost=cost, cost_edge_multiplier=1.5) is False


def test_funding_straddle_included():
    t0 = datetime(2026, 8, 9, 0, 0, tzinfo=UTC)
    funding_time = t0 + timedelta(minutes=10)
    cost_bps = funding_cost_if_straddled(
        position_open_time=t0, time_stop_s=15 * 60, next_funding_time=funding_time, funding_rate_bps=4.0
    )
    assert cost_bps == 4.0


def test_funding_not_straddled_when_beyond_time_stop():
    t0 = datetime(2026, 8, 9, 0, 0, tzinfo=UTC)
    funding_time = t0 + timedelta(minutes=20)  # beyond 15m time stop
    cost_bps = funding_cost_if_straddled(
        position_open_time=t0, time_stop_s=15 * 60, next_funding_time=funding_time, funding_rate_bps=4.0
    )
    assert cost_bps == 0.0


def test_funding_not_straddled_when_already_past():
    t0 = datetime(2026, 8, 9, 0, 0, tzinfo=UTC)
    funding_time = t0 - timedelta(minutes=1)
    cost_bps = funding_cost_if_straddled(
        position_open_time=t0, time_stop_s=15 * 60, next_funding_time=funding_time, funding_rate_bps=4.0
    )
    assert cost_bps == 0.0
