"""In-dashboard backtest job runner — DASHBOARD_STRATEGY_LAB.md §2 / L4.

Candle backtests are sanity-only. Results always carry that banner. Jobs run
inside the process at bounded concurrency and must never starve the live loop.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from scalping.backtest.candle_backtester import BacktestResult, run_candle_backtest
from scalping.config.frozen import FrozenParams
from scalping.config.settings import EffectiveConfig
from scalping.domain.models import Candle, Side

SANITY_BANNER = (
    "Candle-level simulation. Maker fill probability, queue position and "
    "intrabar stop sequencing are approximated. This result is NOT evidence of "
    "live edge — see paper campaign."
)


class BacktestJobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class BacktestJob:
    job_id: str
    preset_id: str
    preset_version: int
    symbols: list[str]
    date_from: datetime
    date_to: datetime
    mode: str  # CANDLE | REPLAY
    status: BacktestJobStatus
    progress: float
    result: dict[str, Any] | None
    created_at: datetime
    config_hash: str
    error: str | None = None
    data_checksum: str | None = None


@dataclass
class BacktestCompareRow:
    metric: str
    values: dict[str, float | int | None]


def summarize_backtest(result: BacktestResult) -> dict[str, Any]:
    rs = [t.r_multiple for t in result.trades]
    wins = sum(1 for r in rs if r > 0)
    n = len(rs)
    gross_win = sum(r for r in rs if r > 0)
    gross_loss = sum(-r for r in rs if r <= 0)
    pf = None
    if gross_loss > 0:
        pf = gross_win / gross_loss
    elif gross_win > 0:
        pf = float("inf")
    return {
        "banner": SANITY_BANNER,
        "n_trades": n,
        "win_rate": (wins / n) if n else None,
        "profit_factor": pf,
        "net_expectancy_r": (sum(rs) / n) if n else None,
        "avg_r": (sum(rs) / n) if n else None,
        "max_dd_r": result.max_drawdown_r if hasattr(result, "max_drawdown_r") else None,
        "rejection_histogram": dict(getattr(result, "rejection_counts", {}) or {}),
    }


def data_checksum(candles_1m: list[Candle], candles_5m: list[Candle]) -> str:
    payload = [
        (c.symbol, c.open_time.isoformat(), c.close, c.quote_volume) for c in candles_1m
    ] + [
        (c.symbol, c.open_time.isoformat(), c.close, c.quote_volume) for c in candles_5m
    ]
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def compare_jobs(jobs: list[BacktestJob]) -> list[BacktestCompareRow]:
    """Side-by-side metrics for 2+ completed runs."""
    completed = [j for j in jobs if j.status is BacktestJobStatus.COMPLETED and j.result]
    if len(completed) < 2:
        raise ValueError("compare requires ≥2 completed jobs")
    metrics = [
        "n_trades", "win_rate", "profit_factor", "net_expectancy_r", "avg_r",
    ]
    rows: list[BacktestCompareRow] = []
    for m in metrics:
        values = {j.job_id: j.result.get(m) if j.result else None for j in completed}
        rows.append(BacktestCompareRow(metric=m, values=values))
    return rows


@dataclass
class BacktestJobRunner:
    """In-process queue with concurrency=1 by default."""

    max_concurrency: int = 1
    allow_in_live: bool = False
    _jobs: dict[str, BacktestJob] = field(default_factory=dict)
    _queue: asyncio.Queue | None = None
    _workers: list[asyncio.Task] = field(default_factory=list)
    _environment: str = "paper"

    def __post_init__(self) -> None:
        self._queue = asyncio.Queue()

    def set_environment(self, environment: str) -> None:
        self._environment = environment

    def get(self, job_id: str) -> BacktestJob | None:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[BacktestJob]:
        return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def enqueue(
        self,
        *,
        preset_id: str,
        preset_version: int,
        symbols: list[str],
        date_from: datetime,
        date_to: datetime,
        config: EffectiveConfig,
        candles_1m: list[Candle],
        candles_5m: list[Candle],
        mode: str = "CANDLE",
        created_at: datetime,
    ) -> BacktestJob:
        if self._environment == "live" and not self.allow_in_live:
            raise RuntimeError("backtests refused while mode=LIVE (allow_backtest_in_live=false)")
        job = BacktestJob(
            job_id=str(uuid4()),
            preset_id=preset_id,
            preset_version=preset_version,
            symbols=symbols,
            date_from=date_from,
            date_to=date_to,
            mode=mode,
            status=BacktestJobStatus.QUEUED,
            progress=0.0,
            result=None,
            created_at=created_at,
            config_hash=config.config_hash(),
            data_checksum=data_checksum(candles_1m, candles_5m),
        )
        self._jobs[job.job_id] = job
        assert self._queue is not None
        self._queue.put_nowait((job.job_id, config, candles_1m, candles_5m))
        return job

    async def start(self) -> None:
        for _ in range(self.max_concurrency):
            self._workers.append(asyncio.create_task(self._worker()))

    async def stop(self) -> None:
        for t in self._workers:
            t.cancel()
        self._workers.clear()

    async def run_one_sync(
        self,
        job: BacktestJob,
        config: EffectiveConfig,
        candles_1m: list[Candle],
        candles_5m: list[Candle],
        frozen: FrozenParams | None = None,
    ) -> BacktestJob:
        """Synchronous path for tests — no worker loop required."""
        job.status = BacktestJobStatus.RUNNING
        job.progress = 0.5
        try:
            result = run_candle_backtest(
                candles_1m, candles_5m, config, frozen, (Side.LONG, Side.SHORT)
            )
            job.result = summarize_backtest(result)
            job.progress = 1.0
            job.status = BacktestJobStatus.COMPLETED
        except Exception as exc:
            job.status = BacktestJobStatus.FAILED
            job.error = str(exc)
        return job

    async def _worker(self) -> None:
        assert self._queue is not None
        while True:
            job_id, config, c1, c5 = await self._queue.get()
            job = self._jobs[job_id]
            await self.run_one_sync(job, config, c1, c5)
            self._queue.task_done()
