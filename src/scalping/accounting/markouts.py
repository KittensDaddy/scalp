"""Maker adverse-selection instrumentation — strategy-caems.md §Adverse-selection
instrumentation. Computes markouts (mid price at +5s/+30s minus fill price) and
implements the pre-registered maker/taker decision rule as code, not as a note
someone has to remember to act on.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

from scalping.domain.models import Side


def markout_bps(*, fill_price: float, mid_at_offset: float, side: Side) -> float:
    """Positive = price moved in the position's favor after fill."""
    move = mid_at_offset - fill_price
    if side is Side.SHORT:
        move = -move
    return move / fill_price * 10_000


def markout_r(*, markout_bps_value: float, fill_price: float, stop_distance: float) -> float:
    price_move = markout_bps_value / 10_000 * fill_price
    return price_move / stop_distance


@dataclass(frozen=True)
class MakerTakerDecision:
    resolved: bool
    switch_to_taker: bool
    avg_maker_30s_bps: float | None
    avg_taker_30s_bps: float | None
    detail: str


def decide_maker_vs_taker(
    *,
    maker_markouts_30s_bps: list[float],
    taker_markouts_30s_bps: list[float],
    fee_difference_bps: float,
    min_total_attempts: int = 300,
) -> MakerTakerDecision:
    """strategy-caems.md, pre-registered: "after >=300 entry attempts in paper, if
    maker fills show 30s markout worse than taker-convert fills by more than the
    maker/taker fee difference, switch default entry to taker-if-spread<=... Do not
    decide this from intuition." — this function is that rule, callable.
    """
    total = len(maker_markouts_30s_bps) + len(taker_markouts_30s_bps)
    if total < min_total_attempts:
        return MakerTakerDecision(
            resolved=False, switch_to_taker=False, avg_maker_30s_bps=None, avg_taker_30s_bps=None,
            detail=f"only {total} entry attempts recorded (need >= {min_total_attempts})",
        )

    avg_maker = mean(maker_markouts_30s_bps) if maker_markouts_30s_bps else 0.0
    avg_taker = mean(taker_markouts_30s_bps) if taker_markouts_30s_bps else 0.0
    switch = avg_maker < (avg_taker - fee_difference_bps)
    detail = (
        f"avg_maker_30s={avg_maker:.2f}bps, avg_taker_30s={avg_taker:.2f}bps, "
        f"fee_diff={fee_difference_bps:.2f}bps -> "
        f"{'switch to taker default' if switch else 'keep maker default'}"
    )
    return MakerTakerDecision(
        resolved=True, switch_to_taker=switch,
        avg_maker_30s_bps=avg_maker, avg_taker_30s_bps=avg_taker, detail=detail,
    )
