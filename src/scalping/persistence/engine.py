"""Async engine/session factory + async write queue.

A single background writer task drains a queue and commits in the calling order,
so hot-path code (strategy eval, OMS) never blocks on a DB round-trip — it just
enqueues a callable. `PersistenceWriter.flush()` is used by tests and by graceful
shutdown to guarantee everything queued has landed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from scalping.persistence.models import Base

WriteJob = Callable[[AsyncSession], Awaitable[None]]


def make_engine(database_url: str):
    if database_url.startswith("sqlite+aiosqlite:///./"):
        rel = database_url.removeprefix("sqlite+aiosqlite:///./")
        Path(rel).parent.mkdir(parents=True, exist_ok=True)
    return create_async_engine(database_url, future=True)


async def init_db(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


class PersistenceWriter:
    """Serializes writes through one queue/session so callers never block."""

    def __init__(self, engine) -> None:
        self._sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
        self._queue: asyncio.Queue[WriteJob] = asyncio.Queue()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        await self.flush()
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def enqueue(self, job: WriteJob) -> None:
        self._queue.put_nowait(job)

    async def flush(self) -> None:
        await self._queue.join()

    async def _run(self) -> None:
        while True:
            job = await self._queue.get()
            try:
                async with self._sessionmaker() as session:
                    await job(session)
                    await session.commit()
            finally:
                self._queue.task_done()
