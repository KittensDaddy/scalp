"""Round-trip cost model.

strategy-caems.md: execution_floor = 3*spread + 2*slippage_buffer (used for stop
sizing in the CAEMS engine, P3). This module computes the *cost gate* input — the
round-trip cost CAEMS condition 12 compares expected gross edge against — plus
funding awareness per PLAN_OF_ACTION.md §3: "positions whose remaining time stop
straddles a funding timestamp include expected funding in the cost gate."
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from scalping.config.settings import CostConfig


@dataclass(frozen=True)
class CostBreakdown:
    entry_fee_bps: float
    exit_fee_bps: float
    spread_cost_bps: float
    slippage_bps: float
    funding_bps: float

    @property
    def total_bps(self) -> float:
        return (
            self.entry_fee_bps
            + self.exit_fee_bps
            + self.spread_cost_bps
            + self.slippage_bps
            + self.funding_bps
        )


def compute_round_trip_cost(
    *,
    cost_cfg: CostConfig,
    spread_bps: float,
    is_maker_entry: bool = True,
    exit_is_taker: bool = True,
    funding_bps: float = 0.0,
) -> CostBreakdown:
    entry_fee = cost_cfg.maker_fee_bps if is_maker_entry else cost_cfg.taker_fee_bps
    exit_fee = cost_cfg.taker_fee_bps if exit_is_taker else cost_cfg.maker_fee_bps
    return CostBreakdown(
        entry_fee_bps=entry_fee,
        exit_fee_bps=exit_fee,
        spread_cost_bps=spread_bps,
        slippage_bps=cost_cfg.safety_buffer_bps,
        funding_bps=funding_bps,
    )


def cost_gate_passed(
    *, expected_gross_edge_bps: float, cost: CostBreakdown, cost_edge_multiplier: float
) -> bool:
    """CAEMS condition 12: expected_gross_edge >= cost_edge_multiplier * round_trip_cost."""
    return expected_gross_edge_bps >= cost_edge_multiplier * cost.total_bps


def funding_cost_if_straddled(
    *,
    position_open_time: datetime,
    time_stop_s: int,
    next_funding_time: datetime,
    funding_rate_bps: float,
) -> float:
    """Returns `funding_rate_bps` if the position's remaining time stop straddles
    `next_funding_time`, else 0.0. A scalp that closes before funding pays nothing;
    a stalled trade held through the funding timestamp pays the rate."""
    time_stop_deadline = position_open_time + timedelta(seconds=time_stop_s)
    if position_open_time <= next_funding_time <= time_stop_deadline:
        return funding_rate_bps
    return 0.0
