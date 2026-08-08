"""Entry order flow — strategy-caems.md §Order flow, implemented verbatim:

1. Post-only maker entry at best bid (long) / best ask (short).
2. TTL 3s.
3. If partially filled, cancel remainder.
4. Re-evaluate with current book/signal/risk/cost.
5. Convert to taker only if remaining_edge > taker_cost + safety_buffer.
6. Otherwise abandon.
7. After fill: place protective stop + take-profit (execution/protection.py) —
   entry is not protected until both are ACKed.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime

from scalping.config.settings import CostConfig
from scalping.costmodel.cost import compute_round_trip_cost
from scalping.domain.models import EntryOutcome, OrderStatus, Side
from scalping.execution.ports import ExchangePort, OrderStatusInfo


@dataclass(frozen=True)
class EntryAttemptResult:
    outcome: EntryOutcome
    filled_quantity: float
    avg_fill_price: float | None
    fill_time: datetime | None


async def run_entry_flow(
    *,
    port: ExchangePort,
    symbol: str,
    side: Side,
    price: float,
    quantity: float,
    client_order_id: str,
    ttl_s: float,
    cost_cfg: CostConfig,
    spread_bps: float,
    remaining_edge_bps: float,
    now: datetime,
) -> EntryAttemptResult:
    await port.place_maker_entry(symbol, side, price, quantity, client_order_id)
    await asyncio.sleep(ttl_s)
    status = await port.query_order(symbol, client_order_id)

    if status.status == OrderStatus.FILLED:
        return EntryAttemptResult(
            outcome=EntryOutcome.MAKER_FILL, filled_quantity=status.filled_quantity,
            avg_fill_price=status.avg_fill_price, fill_time=now,
        )

    # Not fully filled by TTL — cancel whatever remains resting on the book.
    if status.status in (OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED):
        await port.cancel_order(symbol, client_order_id)

    remaining_qty = quantity - status.filled_quantity
    taker_cost = compute_round_trip_cost(
        cost_cfg=cost_cfg, spread_bps=spread_bps, is_maker_entry=False
    )
    should_convert = (
        remaining_qty > 0
        and remaining_edge_bps > taker_cost.total_bps + cost_cfg.safety_buffer_bps
    )

    if not should_convert:
        outcome = EntryOutcome.PARTIAL if status.filled_quantity > 0 else EntryOutcome.ABANDONED
        fill_time = now if status.filled_quantity > 0 else None
        return EntryAttemptResult(
            outcome=outcome, filled_quantity=status.filled_quantity,
            avg_fill_price=status.avg_fill_price, fill_time=fill_time,
        )

    taker_client_id = client_order_id + "-taker"
    taker_status = await port.place_taker_entry(symbol, side, remaining_qty, taker_client_id)
    total_filled = status.filled_quantity + taker_status.filled_quantity
    if total_filled <= 0:
        return EntryAttemptResult(
            outcome=EntryOutcome.ABANDONED, filled_quantity=0.0,
            avg_fill_price=None, fill_time=None,
        )
    blended_avg = _blended_avg_price(status, taker_status)
    return EntryAttemptResult(
        outcome=EntryOutcome.TAKER_CONVERT, filled_quantity=total_filled,
        avg_fill_price=blended_avg, fill_time=now,
    )


def _blended_avg_price(a: OrderStatusInfo, b: OrderStatusInfo) -> float | None:
    total_qty = a.filled_quantity + b.filled_quantity
    if total_qty <= 0:
        return None
    a_notional = (a.avg_fill_price or 0.0) * a.filled_quantity
    b_notional = (b.avg_fill_price or 0.0) * b.filled_quantity
    return (a_notional + b_notional) / total_qty
