from __future__ import annotations

from datetime import UTC, datetime

from scalping.config.settings import CostConfig
from scalping.domain.models import EntryOutcome, OrderStatus, Side
from scalping.execution.entry_flow import run_entry_flow
from scalping.execution.ports import OrderStatusInfo

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


class FakePort:
    def __init__(self, *, query_result: OrderStatusInfo, taker_result: OrderStatusInfo | None = None):
        self.query_result = query_result
        self.taker_result = taker_result
        self.placed_maker: list[tuple] = []
        self.cancelled: list[tuple] = []
        self.placed_taker: list[tuple] = []

    async def place_maker_entry(self, symbol, side, price, quantity, client_order_id):
        self.placed_maker.append((symbol, side, price, quantity, client_order_id))

    async def cancel_order(self, symbol, client_order_id):
        self.cancelled.append((symbol, client_order_id))

    async def query_order(self, symbol, client_order_id):
        return self.query_result

    async def place_taker_entry(self, symbol, side, quantity, client_order_id):
        self.placed_taker.append((symbol, side, quantity, client_order_id))
        return self.taker_result


async def test_full_maker_fill_no_cancel():
    port = FakePort(query_result=OrderStatusInfo(OrderStatus.FILLED, 1.0, 100.0))
    result = await run_entry_flow(
        port=port, symbol="BTCUSDT", side=Side.LONG, price=100.0, quantity=1.0,
        client_order_id="cid1", ttl_s=0, cost_cfg=CostConfig(), spread_bps=1.0,
        remaining_edge_bps=0.0, now=NOW,
    )
    assert result.outcome == EntryOutcome.MAKER_FILL
    assert result.filled_quantity == 1.0
    assert port.cancelled == []


async def test_unfilled_abandoned_when_edge_insufficient():
    port = FakePort(query_result=OrderStatusInfo(OrderStatus.NEW, 0.0, None))
    result = await run_entry_flow(
        port=port, symbol="BTCUSDT", side=Side.LONG, price=100.0, quantity=1.0,
        client_order_id="cid1", ttl_s=0, cost_cfg=CostConfig(), spread_bps=1.0,
        remaining_edge_bps=0.0, now=NOW,
    )
    assert result.outcome == EntryOutcome.ABANDONED
    assert port.cancelled == [("BTCUSDT", "cid1")]
    assert port.placed_taker == []


async def test_unfilled_converts_to_taker_when_edge_sufficient():
    port = FakePort(
        query_result=OrderStatusInfo(OrderStatus.NEW, 0.0, None),
        taker_result=OrderStatusInfo(OrderStatus.FILLED, 1.0, 100.2),
    )
    cost_cfg = CostConfig(maker_fee_bps=2.0, taker_fee_bps=5.0, safety_buffer_bps=1.0)
    result = await run_entry_flow(
        port=port, symbol="BTCUSDT", side=Side.LONG, price=100.0, quantity=1.0,
        client_order_id="cid1", ttl_s=0, cost_cfg=cost_cfg, spread_bps=1.0,
        remaining_edge_bps=100.0, now=NOW,
    )
    assert result.outcome == EntryOutcome.TAKER_CONVERT
    assert result.filled_quantity == 1.0
    assert port.placed_taker[0][3] == "cid1-taker"


async def test_partial_fill_cancel_remainder_and_abandon():
    port = FakePort(query_result=OrderStatusInfo(OrderStatus.PARTIALLY_FILLED, 0.4, 100.0))
    result = await run_entry_flow(
        port=port, symbol="BTCUSDT", side=Side.LONG, price=100.0, quantity=1.0,
        client_order_id="cid1", ttl_s=0, cost_cfg=CostConfig(), spread_bps=1.0,
        remaining_edge_bps=0.0, now=NOW,
    )
    assert result.outcome == EntryOutcome.PARTIAL
    assert result.filled_quantity == 0.4
    assert port.cancelled == [("BTCUSDT", "cid1")]


async def test_partial_fill_converts_remainder_to_taker():
    port = FakePort(
        query_result=OrderStatusInfo(OrderStatus.PARTIALLY_FILLED, 0.4, 100.0),
        taker_result=OrderStatusInfo(OrderStatus.FILLED, 0.6, 100.3),
    )
    cost_cfg = CostConfig(maker_fee_bps=2.0, taker_fee_bps=5.0, safety_buffer_bps=1.0)
    result = await run_entry_flow(
        port=port, symbol="BTCUSDT", side=Side.LONG, price=100.0, quantity=1.0,
        client_order_id="cid1", ttl_s=0, cost_cfg=cost_cfg, spread_bps=1.0,
        remaining_edge_bps=100.0, now=NOW,
    )
    assert result.outcome == EntryOutcome.TAKER_CONVERT
    assert result.filled_quantity == 1.0
    assert port.placed_taker[0][2] == 0.6  # remaining qty only, not full quantity
