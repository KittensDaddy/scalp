"""L4 backtest job runner + compare."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from scalping.backtest.candle_backtester import BacktestResult
from scalping.config.settings import EffectiveConfig
from scalping.domain.models import Candle
from scalping.lab.backtest_jobs import (
    SANITY_BANNER,
    BacktestJobRunner,
    BacktestJobStatus,
    compare_jobs,
    summarize_backtest,
)

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def _candles(n: int = 5) -> list[Candle]:
    out = []
    t0 = NOW
    for i in range(n):
        ts = t0 + timedelta(minutes=i)
        out.append(
            Candle(
                symbol="BTCUSDT", timeframe="1m", open_time=ts,
                close_time=ts + timedelta(minutes=1),
                open=100.0, high=101.0, low=99.0, close=100.5,
                quote_volume=1_000_000.0, is_closed=True,
            )
        )
    return out


@pytest.mark.asyncio
async def test_run_one_sync_completes_with_banner():
    runner = BacktestJobRunner()
    job = runner.enqueue(
        preset_id="meme", preset_version=1, symbols=["BTCUSDT"],
        date_from=NOW, date_to=NOW + timedelta(hours=1),
        config=EffectiveConfig(), candles_1m=_candles(), candles_5m=_candles(2),
        created_at=NOW,
    )
    await runner.run_one_sync(
        job, EffectiveConfig(), _candles(), _candles(2),
    )
    assert job.status is BacktestJobStatus.COMPLETED
    assert job.result is not None
    assert job.result["banner"] == SANITY_BANNER


def test_compare_requires_two_completed():
    runner = BacktestJobRunner()
    j1 = runner.enqueue(
        preset_id="a", preset_version=1, symbols=["BTCUSDT"],
        date_from=NOW, date_to=NOW, config=EffectiveConfig(),
        candles_1m=_candles(), candles_5m=_candles(2), created_at=NOW,
    )
    j1.status = BacktestJobStatus.COMPLETED
    j1.result = summarize_backtest(BacktestResult())
    with pytest.raises(ValueError):
        compare_jobs([j1])


def test_refuse_backtest_in_live_without_flag():
    runner = BacktestJobRunner(allow_in_live=False)
    runner.set_environment("live")
    with pytest.raises(RuntimeError, match="LIVE"):
        runner.enqueue(
            preset_id="a", preset_version=1, symbols=["BTCUSDT"],
            date_from=NOW, date_to=NOW, config=EffectiveConfig(),
            candles_1m=_candles(), candles_5m=_candles(2), created_at=NOW,
        )
