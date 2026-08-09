"""Two wiring paths that decide whether a paper campaign means anything:
the venue seeing the book at WS rate, and cooldowns actually holding a symbol out.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scalping.config.frozen import FrozenParams
from scalping.domain.models import OrderStatus, Side
from scalping.market_data.manager import MarketDataManager
from scalping.market_data.registry import SymbolStateRegistry
from scalping.paper.venue import PaperVenue
from scalping.scanner.cooldowns import CooldownManager

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def _book_msg(symbol="BTCUSDT", bid="99.90", ask="100.10") -> dict:
    return {"s": symbol, "b": bid, "B": "5", "a": ask, "A": "5", "E": 1786000000000}


def test_book_sink_receives_every_ws_update():
    registry = SymbolStateRegistry(FrozenParams())
    seen = []
    mgr = MarketDataManager(
        ws_base="wss://fstream.binance.com", registry=registry, book_sinks=[seen.append]
    )

    mgr.handle_book_ticker_message(_book_msg(bid="99.90"), received_at=NOW)
    mgr.handle_book_ticker_message(_book_msg(bid="99.95"), received_at=NOW)

    assert [b.bid_price for b in seen] == [99.90, 99.95]


def test_registry_still_updated_when_sinks_present():
    registry = SymbolStateRegistry(FrozenParams())
    mgr = MarketDataManager(
        ws_base="wss://fstream.binance.com", registry=registry, book_sinks=[lambda _bt: None]
    )

    mgr.handle_book_ticker_message(_book_msg(), received_at=NOW)

    assert registry.get("BTCUSDT").last_book_ticker.bid_price == 99.90


async def test_venue_wired_as_a_sink_fills_a_resting_maker_order():
    """The whole point of the sink: a GTX order can be crossed between eval
    ticks. Replaying one snapshot per tick can never produce a maker fill."""
    registry = SymbolStateRegistry(FrozenParams())
    venue = PaperVenue()
    mgr = MarketDataManager(
        ws_base="wss://fstream.binance.com", registry=registry, book_sinks=[venue.on_book_ticker]
    )
    await venue.place_maker_entry("BTCUSDT", Side.LONG, 100.0, 1.0, "cid1")

    mgr.handle_book_ticker_message(_book_msg(bid="100.5", ask="100.6"), received_at=NOW)
    assert (await venue.query_order("BTCUSDT", "cid1")).status == OrderStatus.NEW

    # Book trades back down through the resting bid.
    mgr.handle_book_ticker_message(_book_msg(bid="99.8", ask="99.95"), received_at=NOW)
    assert (await venue.query_order("BTCUSDT", "cid1")).status == OrderStatus.FILLED


def test_global_cooldown_is_honoured_not_just_symbol_scope():
    """The API-reconnect cooldown is global scope; a runner that only checks
    symbol scope would silently ignore it."""
    cooldowns = CooldownManager()
    cooldowns.set("global", "*", "api_reconnect", NOW + timedelta(seconds=30))

    assert cooldowns.is_active("global", "*", NOW) is True
    assert cooldowns.is_active("global", "*", NOW + timedelta(seconds=31)) is False
