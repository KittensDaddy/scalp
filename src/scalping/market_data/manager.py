"""MarketDataManager — SCANNER_DASHBOARD_PLAN.md §C/§D.

Owns two independent shard plans (bookTicker on `/public`, kline_1m on `/market`
— never mixed on one connection per PLAN_OF_ACTION.md §2), rebalances them on
universe change with minimal churn (`sharding.py`), and routes parsed messages
into the `SymbolStateRegistry` while feeding the kline contiguity tracker and
latency histogram.

Message routing (`handle_*`) is deliberately separated from connection lifecycle:
the routing methods are plain functions over already-received messages, fully
testable without a socket. Connection lifecycle (opening `BinanceWSConnection`s
per shard, staggered reconnects) is a thin wiring layer on top, using an
injectable shard factory so tests never touch the network — the same pattern
used for `ExchangePort` throughout `execution/`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from scalping.domain.models import BookTicker, Candle
from scalping.exchanges.binance.shapes import check_book_ticker_shape, check_kline_shape
from scalping.exchanges.binance.ws import BinanceWSConnection, StreamCategory
from scalping.market_data.aggregation import StreamingAggregator
from scalping.market_data.klines import ContiguityTracker, Gap
from scalping.market_data.latency import LatencyTracker
from scalping.market_data.registry import SymbolStateRegistry
from scalping.market_data.sharding import ShardPlan, rebalance_shards

ShardFactory = Callable[..., BinanceWSConnection]


@dataclass(frozen=True)
class KlineHandleResult:
    candle: Candle | None
    gap: Gap | None
    candle_5m: Candle | None = None


class MarketDataManager:
    def __init__(
        self,
        *,
        ws_base: str,
        registry: SymbolStateRegistry,
        contiguity: ContiguityTracker | None = None,
        max_streams_per_shard: int = 200,
        shard_factory: ShardFactory = BinanceWSConnection,
        aggregate_5m: bool = True,
        proxy: str | None = None,
    ) -> None:
        self.ws_base = ws_base
        self.registry = registry
        self.contiguity = contiguity or ContiguityTracker()
        self.max_streams_per_shard = max_streams_per_shard
        self.public_plan = ShardPlan()
        self.market_plan = ShardPlan()
        self.latency = LatencyTracker()
        self._shard_factory = shard_factory
        self._connections: dict[tuple[str, int], BinanceWSConnection] = {}
        self.aggregate_5m = aggregate_5m
        self._agg_5m: dict[str, StreamingAggregator] = {}
        self.proxy = proxy

    # -- shard planning ------------------------------------------------------------

    def rebalance(self, universe: set[str]) -> tuple[ShardPlan, ShardPlan]:
        self.public_plan = rebalance_shards(self.public_plan, universe, self.max_streams_per_shard)
        self.market_plan = rebalance_shards(self.market_plan, universe, self.max_streams_per_shard)
        return self.public_plan, self.market_plan

    @staticmethod
    def build_public_streams(symbols: list[str]) -> list[str]:
        return [f"{s.lower()}@bookTicker" for s in symbols]

    @staticmethod
    def build_market_streams(symbols: list[str]) -> list[str]:
        return [f"{s.lower()}@kline_1m" for s in symbols]

    # -- message routing (network-free, directly testable) --------------------------

    def handle_book_ticker_message(self, msg: dict, *, received_at: datetime) -> BookTicker:
        check_book_ticker_shape(msg)
        bt = BookTicker(
            symbol=msg["s"], bid_price=float(msg["b"]), bid_qty=float(msg["B"]),
            ask_price=float(msg["a"]), ask_qty=float(msg["A"]), event_time=received_at,
        )
        self.registry.on_book_ticker(bt)
        exchange_ts = _event_time_from_msg(msg, fallback=received_at)
        self.latency.record("book_ticker", exchange_ts=exchange_ts, local_ts=received_at)
        return bt

    def handle_kline_message(self, msg: dict, *, received_at: datetime) -> KlineHandleResult:
        check_kline_shape(msg)
        k = msg["k"]
        if not k.get("x"):
            return KlineHandleResult(candle=None, gap=None)
        symbol = msg.get("s") or k.get("s")
        candle = Candle(
            symbol=symbol, timeframe="1m",
            open_time=datetime.fromtimestamp(k["t"] / 1000, tz=UTC),
            close_time=datetime.fromtimestamp(k["T"] / 1000, tz=UTC),
            open=float(k["o"]), high=float(k["h"]), low=float(k["l"]), close=float(k["c"]),
            quote_volume=float(k["q"]),
        )
        gap = self.contiguity.observe(symbol, candle.open_time)
        self.registry.on_kline_1m_closed(candle)
        candle_5m = None
        if self.aggregate_5m:
            agg = self._agg_5m.setdefault(symbol, StreamingAggregator("5m"))
            candle_5m = agg.on_1m_candle(candle)
            if candle_5m is not None:
                self.registry.on_kline_5m_closed(candle_5m)
        exchange_ts = _event_time_from_msg(msg, fallback=received_at)
        self.latency.record("kline_1m", exchange_ts=exchange_ts, local_ts=received_at)
        return KlineHandleResult(candle=candle, gap=gap, candle_5m=candle_5m)

    # -- connection lifecycle (thin; not exercised by unit tests) -------------------

    def _on_book_ticker(self, m: dict) -> None:
        self.handle_book_ticker_message(m, received_at=datetime.now(UTC))

    def _on_kline(self, m: dict) -> None:
        self.handle_kline_message(m, received_at=datetime.now(UTC))

    def build_connections(self) -> dict[tuple[str, int], BinanceWSConnection]:
        self._connections = {}
        for shard_id, symbols in self.public_plan.assignments.items():
            self._connections[("public", shard_id)] = self._shard_factory(
                ws_base=self.ws_base, category=StreamCategory.PUBLIC,
                streams=self.build_public_streams(symbols), on_message=self._on_book_ticker,
                proxy=self.proxy,
            )
        for shard_id, symbols in self.market_plan.assignments.items():
            self._connections[("market", shard_id)] = self._shard_factory(
                ws_base=self.ws_base, category=StreamCategory.MARKET,
                streams=self.build_market_streams(symbols), on_message=self._on_kline,
                proxy=self.proxy,
            )
        return self._connections


def _event_time_from_msg(msg: dict, *, fallback: datetime) -> datetime:
    """Binance event messages carry `E` (event time, ms) at the top level; falls
    back to local receipt time if absent (e.g. REST-sourced test fixtures)."""
    e = msg.get("E")
    if e is None:
        return fallback
    return datetime.fromtimestamp(e / 1000, tz=UTC)
