"""ExchangePort — the interface OMS/protection/reconcile code depends on.

Deliberately exchange-agnostic: the real Binance adapter (P2/P6) and the paper venue
(P8) both implement this, and PLAN_OF_ACTION.md §5 requires "one execution pipeline
for all modes" — only this port's implementation differs between them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from scalping.domain.models import OrderStatus, Side


@dataclass(frozen=True)
class OrderStatusInfo:
    status: OrderStatus
    filled_quantity: float
    avg_fill_price: float | None


@dataclass(frozen=True)
class AlgoAck:
    algo_id: str
    ack_time: object  # datetime; loosely typed to avoid import cycles in Protocol


@dataclass(frozen=True)
class ExchangePosition:
    symbol: str
    side: Side
    quantity: float


@dataclass(frozen=True)
class ExchangeOpenAlgoOrder:
    symbol: str
    algo_type: str  # "STOP_MARKET" | "TAKE_PROFIT_MARKET"


class ExchangePort(Protocol):
    async def place_maker_entry(
        self, symbol: str, side: Side, price: float, quantity: float, client_order_id: str
    ) -> None: ...

    async def cancel_order(self, symbol: str, client_order_id: str) -> None: ...

    async def query_order(self, symbol: str, client_order_id: str) -> OrderStatusInfo: ...

    async def place_taker_entry(
        self, symbol: str, side: Side, quantity: float, client_order_id: str
    ) -> OrderStatusInfo: ...

    async def place_stop(
        self, symbol: str, side: Side, stop_price: float, quantity: float, client_algo_id: str
    ) -> AlgoAck: ...

    async def place_take_profit(
        self, symbol: str, side: Side, tp_price: float, quantity: float, client_algo_id: str
    ) -> AlgoAck: ...

    async def amend_stop(
        self, symbol: str, client_algo_id: str, new_stop_price: float
    ) -> AlgoAck: ...

    async def place_reduce_only_market_close(
        self, symbol: str, side: Side, quantity: float
    ) -> OrderStatusInfo: ...

    async def get_open_positions(self) -> list[ExchangePosition]: ...

    async def get_open_algo_orders(self, symbol: str) -> list[ExchangeOpenAlgoOrder]: ...
