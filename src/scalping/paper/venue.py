"""Paper trading venue — implements `ExchangePort` on the same execution pipeline
used for testnet/live (PLAN_OF_ACTION.md §8: "one execution pipeline for all
modes; only the venue adapter differs").

Fill simulation is deliberately simple and stated as such: a resting GTX maker
order fills when the opposing best price crosses through it (bookTicker-driven);
taker orders and reduce-only closes fill immediately at the current best
bid/ask; stop/take-profit algo orders trigger the same way stops do on a real
exchange — against best bid (for longs) / best ask (for shorts). This is more
realistic than the candle backtester (P5) because it is driven by live top-of-book
data rather than OHLC bars, but it is still not execution-realistic in the sense
of modeling queue position — see PLAN §5 for why only paper/testnet forward results
count as evidence, never this or the candle backtester.
"""

from __future__ import annotations

from dataclasses import dataclass

from scalping.domain.models import BookTicker, OrderStatus, Side
from scalping.execution.ports import (
    AlgoAck,
    ExchangeOpenAlgoOrder,
    ExchangePosition,
    OrderStatusInfo,
)


@dataclass
class _RestingOrder:
    symbol: str
    side: Side
    price: float
    quantity: float
    filled_quantity: float = 0.0
    status: OrderStatus = OrderStatus.NEW


@dataclass
class _AlgoOrder:
    symbol: str
    side: Side
    algo_type: str  # "STOP_MARKET" | "TAKE_PROFIT_MARKET"
    trigger_price: float
    quantity: float


@dataclass
class _Position:
    symbol: str
    side: Side
    quantity: float


class PaperVenue:
    def __init__(self) -> None:
        self._orders: dict[str, _RestingOrder] = {}
        self._algo_orders: dict[str, _AlgoOrder] = {}
        self._positions: dict[str, _Position] = {}
        self._last_book: dict[str, BookTicker] = {}

    # -- market data feed --------------------------------------------------------

    def on_book_ticker(self, bt: BookTicker) -> None:
        self._last_book[bt.symbol] = bt
        self._try_fill_resting_orders(bt)
        self._try_trigger_algo_orders(bt)

    def _try_fill_resting_orders(self, bt: BookTicker) -> None:
        for order in self._orders.values():
            if order.symbol != bt.symbol or order.status != OrderStatus.NEW:
                continue
            long_crossed = order.side is Side.LONG and bt.ask_price <= order.price
            short_crossed = order.side is Side.SHORT and bt.bid_price >= order.price
            if long_crossed or short_crossed:
                self._fill_order(order, order.quantity)

    def _fill_order(self, order: _RestingOrder, quantity: float) -> None:
        order.filled_quantity += quantity
        order.status = (
            OrderStatus.FILLED
            if order.filled_quantity >= order.quantity
            else OrderStatus.PARTIALLY_FILLED
        )
        self._apply_position_delta(order.symbol, order.side, quantity)

    def _apply_position_delta(self, symbol: str, side: Side, quantity: float) -> None:
        existing = self._positions.get(symbol)
        if existing is None:
            self._positions[symbol] = _Position(symbol, side, quantity)
            return
        if existing.side == side:
            existing.quantity += quantity
        else:
            existing.quantity -= quantity
            if existing.quantity < 0:
                existing.side = Side.SHORT if existing.side is Side.LONG else Side.LONG
                existing.quantity = abs(existing.quantity)
            elif existing.quantity == 0:
                del self._positions[symbol]

    def _try_trigger_algo_orders(self, bt: BookTicker) -> None:
        triggered = []
        for cid, algo in self._algo_orders.items():
            if algo.symbol != bt.symbol:
                continue
            if self._algo_hit(algo, bt):
                triggered.append(cid)
        for cid in triggered:
            algo = self._algo_orders.pop(cid)
            closing_side = Side.SHORT if algo.side is Side.LONG else Side.LONG
            self._apply_position_delta(algo.symbol, closing_side, algo.quantity)

    @staticmethod
    def _algo_hit(algo: _AlgoOrder, bt: BookTicker) -> bool:
        """Direction depends on both position side and algo type: a stop triggers
        against adverse price movement, a take-profit against favorable movement —
        opposite directions for the same position side."""
        is_long = algo.side is Side.LONG
        if algo.algo_type == "STOP_MARKET":
            if is_long:
                return bt.bid_price <= algo.trigger_price
            return bt.ask_price >= algo.trigger_price
        if is_long:
            return bt.ask_price >= algo.trigger_price
        return bt.bid_price <= algo.trigger_price

    # -- ExchangePort implementation ----------------------------------------------

    async def place_maker_entry(
        self, symbol: str, side: Side, price: float, quantity: float, client_order_id: str
    ) -> None:
        self._orders[client_order_id] = _RestingOrder(symbol, side, price, quantity)

    async def cancel_order(self, symbol: str, client_order_id: str) -> None:
        order = self._orders.get(client_order_id)
        if order is not None and order.status == OrderStatus.NEW:
            order.status = OrderStatus.CANCELED

    async def query_order(self, symbol: str, client_order_id: str) -> OrderStatusInfo:
        order = self._orders.get(client_order_id)
        if order is None:
            return OrderStatusInfo(OrderStatus.REJECTED, 0.0, None)
        return OrderStatusInfo(order.status, order.filled_quantity, order.price)

    async def place_taker_entry(
        self, symbol: str, side: Side, quantity: float, client_order_id: str
    ) -> OrderStatusInfo:
        bt = self._last_book.get(symbol)
        price = (bt.ask_price if side is Side.LONG else bt.bid_price) if bt else 0.0
        self._orders[client_order_id] = _RestingOrder(
            symbol, side, price, quantity, filled_quantity=quantity, status=OrderStatus.FILLED
        )
        self._apply_position_delta(symbol, side, quantity)
        return OrderStatusInfo(OrderStatus.FILLED, quantity, price)

    async def place_stop(
        self, symbol: str, side: Side, stop_price: float, quantity: float, client_algo_id: str
    ) -> AlgoAck:
        self._algo_orders[client_algo_id] = _AlgoOrder(
            symbol, side, "STOP_MARKET", stop_price, quantity
        )
        return AlgoAck(algo_id=client_algo_id, ack_time=None)

    async def place_take_profit(
        self, symbol: str, side: Side, tp_price: float, quantity: float, client_algo_id: str
    ) -> AlgoAck:
        self._algo_orders[client_algo_id] = _AlgoOrder(
            symbol, side, "TAKE_PROFIT_MARKET", tp_price, quantity
        )
        return AlgoAck(algo_id=client_algo_id, ack_time=None)

    async def amend_stop(self, symbol: str, client_algo_id: str, new_stop_price: float) -> AlgoAck:
        algo = self._algo_orders.get(client_algo_id)
        if algo is not None:
            algo.trigger_price = new_stop_price
        return AlgoAck(algo_id=client_algo_id, ack_time=None)

    async def place_reduce_only_market_close(
        self, symbol: str, side: Side, quantity: float
    ) -> OrderStatusInfo:
        bt = self._last_book.get(symbol)
        price = (bt.bid_price if side is Side.LONG else bt.ask_price) if bt else 0.0
        closing_side = Side.SHORT if side is Side.LONG else Side.LONG
        self._apply_position_delta(symbol, closing_side, quantity)
        return OrderStatusInfo(OrderStatus.FILLED, quantity, price)

    async def get_open_positions(self) -> list[ExchangePosition]:
        return [ExchangePosition(p.symbol, p.side, p.quantity) for p in self._positions.values()]

    async def get_open_algo_orders(self, symbol: str) -> list[ExchangeOpenAlgoOrder]:
        return [
            ExchangeOpenAlgoOrder(a.symbol, a.algo_type)
            for a in self._algo_orders.values()
            if a.symbol == symbol
        ]
