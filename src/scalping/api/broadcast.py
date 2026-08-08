"""Generic in-process pub/sub for WS push — scanner deltas, position updates,
system events (SCANNER_DASHBOARD_PLAN.md §I: `/stream/scanner`, `/stream/positions`,
`/stream/system`).

Each WS connection subscribes its own `asyncio.Queue`; `publish` fans out to every
subscriber. This is intentionally process-local (no external broker) — matching
PLAN_OF_ACTION.md's "no microservices" constraint.
"""

from __future__ import annotations

import asyncio
from typing import Any


class Broadcaster:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = {}

    def subscribe(self, channel: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.setdefault(channel, set()).add(q)
        return q

    def unsubscribe(self, channel: str, q: asyncio.Queue) -> None:
        self._subscribers.get(channel, set()).discard(q)

    async def publish(self, channel: str, message: Any) -> None:
        for q in list(self._subscribers.get(channel, set())):
            await q.put(message)
