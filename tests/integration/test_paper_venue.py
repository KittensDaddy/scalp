from __future__ import annotations

from datetime import UTC, datetime

from scalping.domain.models import BookTicker, OrderStatus, Side
from scalping.paper.venue import PaperVenue

T = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def _bt(symbol="BTCUSDT", bid=99.9, ask=100.1) -> BookTicker:
    return BookTicker(symbol=symbol, bid_price=bid, bid_qty=10, ask_price=ask, ask_qty=10, event_time=T)


async def test_maker_long_order_does_not_fill_until_crossed():
    venue = PaperVenue()
    await venue.place_maker_entry("BTCUSDT", Side.LONG, 99.9, 1.0, "cid1")
    venue.on_book_ticker(_bt(bid=99.5, ask=100.5))  # ask above order price -> no fill
    status = await venue.query_order("BTCUSDT", "cid1")
    assert status.status == OrderStatus.NEW


async def test_maker_long_order_fills_when_ask_crosses():
    venue = PaperVenue()
    await venue.place_maker_entry("BTCUSDT", Side.LONG, 100.0, 1.0, "cid1")
    venue.on_book_ticker(_bt(bid=99.8, ask=99.95))  # ask <= order price
    status = await venue.query_order("BTCUSDT", "cid1")
    assert status.status == OrderStatus.FILLED
    assert status.filled_quantity == 1.0
    positions = await venue.get_open_positions()
    assert positions[0].symbol == "BTCUSDT"
    assert positions[0].side == Side.LONG
    assert positions[0].quantity == 1.0


async def test_maker_short_order_fills_when_bid_crosses():
    venue = PaperVenue()
    await venue.place_maker_entry("BTCUSDT", Side.SHORT, 100.0, 1.0, "cid1")
    venue.on_book_ticker(_bt(bid=100.1, ask=100.2))  # bid >= order price
    status = await venue.query_order("BTCUSDT", "cid1")
    assert status.status == OrderStatus.FILLED


async def test_cancel_prevents_future_fill():
    venue = PaperVenue()
    await venue.place_maker_entry("BTCUSDT", Side.LONG, 100.0, 1.0, "cid1")
    await venue.cancel_order("BTCUSDT", "cid1")
    venue.on_book_ticker(_bt(bid=99.8, ask=99.9))  # would have crossed
    status = await venue.query_order("BTCUSDT", "cid1")
    assert status.status == OrderStatus.CANCELED


async def test_taker_entry_fills_immediately_at_book_price():
    venue = PaperVenue()
    venue.on_book_ticker(_bt(bid=99.9, ask=100.1))
    status = await venue.place_taker_entry("BTCUSDT", Side.LONG, 1.0, "cid-taker")
    assert status.status == OrderStatus.FILLED
    assert status.avg_fill_price == 100.1  # buys at ask


async def test_stop_triggers_and_closes_long_position():
    venue = PaperVenue()
    await venue.place_taker_entry("BTCUSDT", Side.LONG, 1.0, "entry")
    await venue.place_stop("BTCUSDT", Side.LONG, 99.0, 1.0, "stop-cid")
    venue.on_book_ticker(_bt(bid=98.9, ask=99.0))  # bid <= stop trigger
    positions = await venue.get_open_positions()
    assert positions == []


async def test_take_profit_triggers_and_closes_short_position():
    venue = PaperVenue()
    await venue.place_taker_entry("BTCUSDT", Side.SHORT, 1.0, "entry")
    await venue.place_take_profit("BTCUSDT", Side.SHORT, 98.0, 1.0, "tp-cid")
    venue.on_book_ticker(_bt(bid=97.9, ask=98.0))  # ask <= tp trigger for short close... wait short TP triggers on ask>=? let's mirror
    positions = await venue.get_open_positions()
    assert positions == []


async def test_amend_stop_changes_trigger_price():
    venue = PaperVenue()
    await venue.place_taker_entry("BTCUSDT", Side.LONG, 1.0, "entry")
    await venue.place_stop("BTCUSDT", Side.LONG, 90.0, 1.0, "stop-cid")
    await venue.amend_stop("BTCUSDT", "stop-cid", 99.5)
    venue.on_book_ticker(_bt(bid=99.4, ask=99.5))  # would not have triggered old stop (90) but triggers new
    positions = await venue.get_open_positions()
    assert positions == []


async def test_reduce_only_market_close_flattens_position():
    venue = PaperVenue()
    await venue.place_taker_entry("BTCUSDT", Side.LONG, 1.0, "entry")
    venue.on_book_ticker(_bt())
    await venue.place_reduce_only_market_close("BTCUSDT", Side.LONG, 1.0)
    positions = await venue.get_open_positions()
    assert positions == []


async def test_open_algo_orders_reported_per_symbol():
    venue = PaperVenue()
    await venue.place_stop("BTCUSDT", Side.LONG, 99.0, 1.0, "stop-cid")
    await venue.place_take_profit("BTCUSDT", Side.LONG, 101.0, 1.0, "tp-cid")
    orders = await venue.get_open_algo_orders("BTCUSDT")
    types = {o.algo_type for o in orders}
    assert types == {"STOP_MARKET", "TAKE_PROFIT_MARKET"}
