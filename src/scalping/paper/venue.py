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


@dataclass(frozen=True)
class CloseFill:
    """How a position actually left the book.

    The executor books R against this rather than against the last mark it
    happened to take: a stop triggers exactly when price crosses it, so pricing
    the exit at the previous eval tick's mid understates losses and overstates
    wins by roughly the tick interval's worth of movement.
    """

    symbol: str
    price: float
    reason: str  # "STOP_MARKET" | "TAKE_PROFIT_MARKET" | "REDUCE_ONLY"


class PaperVenue:
    def __init__(self) -> None:
        self._orders: dict[str, _RestingOrder] = {}
        self._algo_orders: dict[str, _AlgoOrder] = {}
        self._positions: dict[str, _Position] = {}
        self._last_book: dict[str, BookTicker] = {}
        # Symbol indexes so a book update touches only that symbol's working
        # orders. This feed runs at WS rate over a 300-symbol universe, so a
        # full scan of every order ever placed would dominate the event loop.
        self._resting_by_symbol: dict[str, set[str]] = {}
        self._algos_by_symbol: dict[str, set[str]] = {}
        self._closes: dict[str, CloseFill] = {}

    # -- market data feed --------------------------------------------------------

    def last_book(self, symbol: str) -> BookTicker | None:
        """Most recent top-of-book seen for `symbol`, or None before first tick."""
        return self._last_book.get(symbol)

    def take_close_fill(self, symbol: str) -> CloseFill | None:
        """Consume the record of how `symbol`'s position was closed, if any."""
        return self._closes.pop(symbol, None)

    def on_book_ticker(self, bt: BookTicker) -> None:
        self._last_book[bt.symbol] = bt
        self._try_fill_resting_orders(bt)
        self._try_trigger_algo_orders(bt)

    def _index_resting(self, client_order_id: str, order: _RestingOrder) -> None:
        self._resting_by_symbol.setdefault(order.symbol, set()).add(client_order_id)

    def _unindex_resting(self, client_order_id: str, symbol: str) -> None:
        working = self._resting_by_symbol.get(symbol)
        if working is None:
            return
        working.discard(client_order_id)
        if not working:
            del self._resting_by_symbol[symbol]

    def _try_fill_resting_orders(self, bt: BookTicker) -> None:
        for cid in list(self._resting_by_symbol.get(bt.symbol, ())):
            order = self._orders.get(cid)
            if order is None or order.status != OrderStatus.NEW:
                self._unindex_resting(cid, bt.symbol)
                continue
            long_crossed = order.side is Side.LONG and bt.ask_price <= order.price
            short_crossed = order.side is Side.SHORT and bt.bid_price >= order.price
            if long_crossed or short_crossed:
                self._fill_order(order, order.quantity)
                self._unindex_resting(cid, bt.symbol)

    def _fill_order(self, order: _RestingOrder, quantity: float) -> None:
        order.filled_quantity += quantity
        order.status = (
            OrderStatus.FILLED
            if order.filled_quantity >= order.quantity
            else OrderStatus.PARTIALLY_FILLED
        )
        self._apply_position_delta(order.symbol, order.side, quantity)

    def _reduce_position(self, symbol: str, quantity: float) -> None:
        """Close up to `quantity` of an open position. Never opens or flips one —
        that is what `reduceOnly` guarantees on the exchange, and a paper close
        that could flip a flat book into a fresh position would silently
        manufacture trades the strategy never asked for."""
        existing = self._positions.get(symbol)
        if existing is None:
            return
        closing = min(quantity, existing.quantity)
        existing.quantity -= closing
        if existing.quantity <= 0:
            del self._positions[symbol]

    def _cancel_algos_for(self, symbol: str) -> None:
        for cid in self._algos_by_symbol.pop(symbol, set()):
            self._algo_orders.pop(cid, None)

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
        for cid in self._algos_by_symbol.get(bt.symbol, ()):
            algo = self._algo_orders.get(cid)
            if algo is not None and self._algo_hit(algo, bt):
                triggered.append(cid)
        for cid in triggered:
            algo = self._algo_orders.get(cid)
            if algo is None:
                continue
            # A triggered stop/TP becomes a market order: it lifts the opposing
            # side, so the fill is the touch at trigger time, not the trigger
            # price. That difference is the gap risk the campaign should see.
            exit_price = bt.bid_price if algo.side is Side.LONG else bt.ask_price
            if self._positions.get(algo.symbol) is not None:
                self._closes[algo.symbol] = CloseFill(
                    symbol=algo.symbol, price=exit_price, reason=algo.algo_type
                )
            self._reduce_position(algo.symbol, algo.quantity)
            # Stop and take-profit are siblings guarding one position. On a real
            # exchange both are reduce-only, so whichever fires first leaves the
            # other unable to do anything. Here the survivor would trigger later
            # against a flat book and open a phantom position, so cancel the
            # whole group — OCO semantics.
            self._cancel_algos_for(algo.symbol)

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
        order = _RestingOrder(symbol, side, price, quantity)
        self._orders[client_order_id] = order
        self._index_resting(client_order_id, order)

    async def cancel_order(self, symbol: str, client_order_id: str) -> None:
        order = self._orders.get(client_order_id)
        if order is not None and order.status == OrderStatus.NEW:
            order.status = OrderStatus.CANCELED
        self._unindex_resting(client_order_id, symbol)

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
        self._algos_by_symbol.setdefault(symbol, set()).add(client_algo_id)
        return AlgoAck(algo_id=client_algo_id, ack_time=None)

    async def place_take_profit(
        self, symbol: str, side: Side, tp_price: float, quantity: float, client_algo_id: str
    ) -> AlgoAck:
        self._algo_orders[client_algo_id] = _AlgoOrder(
            symbol, side, "TAKE_PROFIT_MARKET", tp_price, quantity
        )
        self._algos_by_symbol.setdefault(symbol, set()).add(client_algo_id)
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
        if self._positions.get(symbol) is not None:
            self._closes[symbol] = CloseFill(symbol=symbol, price=price, reason="REDUCE_ONLY")
        self._reduce_position(symbol, quantity)
        # The protective orders guarded a position that no longer exists.
        self._cancel_algos_for(symbol)
        return OrderStatusInfo(OrderStatus.FILLED, quantity, price)

    async def get_open_positions(self) -> list[ExchangePosition]:
        return [ExchangePosition(p.symbol, p.side, p.quantity) for p in self._positions.values()]

    async def get_open_algo_orders(self, symbol: str) -> list[ExchangeOpenAlgoOrder]:
        return [
            ExchangeOpenAlgoOrder(a.symbol, a.algo_type)
            for a in self._algo_orders.values()
            if a.symbol == symbol
        ]
