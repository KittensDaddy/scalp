"""Binance USDS-M Futures WS client on the new (post 2026-04-23) path split.

PLAN_OF_ACTION.md §2: legacy `/ws` & `/stream` retired; new paths are `/public`
(bookTicker), `/market` (klines/mark/depth), `/private` (user stream). "Combined
streams must not mix categories on one connection."

P2 scope is a single-connection-per-category client sufficient for 2 symbols; the
sharded multi-connection `MarketDataManager` for hundreds of symbols is scanner plan
phase S2 and wraps this same category discipline per shard.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from enum import StrEnum

import websockets

from scalping.exchanges.base.errors import WebSocketCategoryMixError

log = logging.getLogger(__name__)


class StreamCategory(StrEnum):
    PUBLIC = "public"    # bookTicker
    MARKET = "market"    # klines, mark price, depth
    PRIVATE = "private"  # user data stream


_CATEGORY_STREAM_PREFIXES: dict[StreamCategory, tuple[str, ...]] = {
    StreamCategory.PUBLIC: ("bookTicker",),
    StreamCategory.MARKET: ("kline_", "markPrice", "depth"),
    StreamCategory.PRIVATE: ("listenKey",),
}


def _category_of(stream: str) -> StreamCategory:
    for category, prefixes in _CATEGORY_STREAM_PREFIXES.items():
        if any(p in stream for p in prefixes):
            return category
    raise ValueError(f"unrecognized stream name: {stream!r}")


def validate_single_category(streams: list[str]) -> StreamCategory:
    """Raise :class:`WebSocketCategoryMixError` if `streams` spans more than one
    category — the invariant PLAN §2 requires per connection."""
    if not streams:
        raise ValueError("at least one stream required")
    categories = {_category_of(s) for s in streams}
    if len(categories) > 1:
        raise WebSocketCategoryMixError(
            f"streams span multiple categories on one connection: {sorted(categories)}"
        )
    return categories.pop()


class BinanceWSConnection:
    """One connection, one category, jittered reconnect with backoff."""

    def __init__(
        self,
        *,
        ws_base: str,
        category: StreamCategory,
        streams: list[str],
        on_message: Callable[[dict], None],
        max_backoff_s: float = 30.0,
        proxy: str | None = None,
        on_disconnect: Callable[[], None] | None = None,
    ) -> None:
        validate_single_category(streams)
        if _category_of(streams[0]) != category:
            raise WebSocketCategoryMixError(
                f"declared category {category} does not match stream {streams[0]!r}"
            )
        self._ws_base = ws_base.rstrip("/")
        self.category = category
        self.streams = streams
        self._on_message = on_message
        self._max_backoff_s = max_backoff_s
        self._proxy = proxy
        self._on_disconnect = on_disconnect
        self._stop = asyncio.Event()

    def _url(self) -> str:
        path = "/" + self.category.value
        joined = "/".join(self.streams)
        return f"{self._ws_base}{path}/stream?streams={joined}"

    def _notify_disconnect(self) -> None:
        """Every connection loss is a data gap, whether the socket errored or the
        server closed it cleanly — both feed the "API reconnect" cooldown."""
        if self._on_disconnect is None:
            return
        try:
            self._on_disconnect()
        except Exception:  # a cooldown hook must never kill the reconnect loop
            log.exception("on_disconnect hook failed for %s", self.category)

    async def run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                # proxy=True → honor HTTP(S)_PROXY env; explicit URL overrides.
                connect_kwargs: dict = {}
                if self._proxy is not None:
                    connect_kwargs["proxy"] = self._proxy
                async with websockets.connect(self._url(), **connect_kwargs) as ws:
                    backoff = 1.0
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        self._on_message(json.loads(raw))
            except (websockets.exceptions.WebSocketException, OSError):
                if self._stop.is_set():
                    break
                self._notify_disconnect()
            else:
                # Clean server close still drops the feed; back off rather than
                # spin, otherwise a server that closes immediately hot-loops.
                if self._stop.is_set():
                    break
                self._notify_disconnect()
            jitter = backoff * (0.5 + 0.5 * _jitter())
            await asyncio.sleep(jitter)
            backoff = min(self._max_backoff_s, backoff * 2)

    def stop(self) -> None:
        self._stop.set()


def _jitter() -> float:
    import random

    return random.random()


async def iter_test_messages(messages: list[dict]) -> AsyncIterator[dict]:
    """Test helper: replays a fixed message list without touching the network."""
    for m in messages:
        yield m
        await asyncio.sleep(0)
