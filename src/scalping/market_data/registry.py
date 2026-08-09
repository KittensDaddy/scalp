"""SymbolState registry — SCANNER_DASHBOARD_PLAN.md §C: "SymbolState Registry
(in-memory, RW-lock-free via single asyncio loop)". Owns per-symbol incremental
indicator state and the latest book ticker; this is the shared state
FeatureEngine (S3) and StrategyRunner (S4) read from.

Single-writer discipline: every method here must only ever be called from the
one asyncio event loop that owns market data — no locks, because there is
exactly one writer, matching the plan's stated design.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from scalping.config.frozen import FrozenParams
from scalping.domain.models import BookTicker, Candle
from scalping.indicators.incremental import ATR, EMA, RollingMedian
from scalping.market_data.book_micro import BookMicroFeatures
from scalping.market_data.staleness import Feed, StalenessWatchdog


@dataclass
class SymbolState:
    symbol: str
    ema_fast_1m: EMA
    ema_slow_1m: EMA
    ema_fast_5m: EMA
    ema_slow_5m: EMA
    atr_1m: ATR
    volume_median_30: RollingMedian
    last_book_ticker: BookTicker | None = None
    last_kline_1m_close_time: datetime | None = None
    last_kline_5m_close_time: datetime | None = None
    last_candle_1m: Candle | None = None
    # Microstructure feature buffers (best-effort without full L2/CVD).
    candles_1m: deque[Candle] = field(default_factory=lambda: deque(maxlen=120))
    book_micro: BookMicroFeatures = field(default_factory=BookMicroFeatures)


def _new_state(symbol: str, frozen: FrozenParams) -> SymbolState:
    return SymbolState(
        symbol=symbol,
        ema_fast_1m=EMA(frozen.ema_fast_1m),
        ema_slow_1m=EMA(frozen.ema_slow_1m),
        ema_fast_5m=EMA(frozen.ema_fast_5m),
        ema_slow_5m=EMA(frozen.ema_slow_5m),
        atr_1m=ATR(frozen.atr_period_1m),
        volume_median_30=RollingMedian(frozen.volume_median_bars),
    )


class SymbolStateRegistry:
    def __init__(self, frozen: FrozenParams, staleness: StalenessWatchdog | None = None) -> None:
        self._frozen = frozen
        self._states: dict[str, SymbolState] = {}
        self.staleness = staleness or StalenessWatchdog()

    def _get_or_create(self, symbol: str) -> SymbolState:
        if symbol not in self._states:
            self._states[symbol] = _new_state(symbol, self._frozen)
        return self._states[symbol]

    def on_book_ticker(self, bt: BookTicker) -> None:
        state = self._get_or_create(bt.symbol)
        state.last_book_ticker = bt
        state.book_micro.on_book(bt)
        self.staleness.record(bt.symbol, Feed.BOOK_TICKER, bt.event_time)

    def on_kline_1m_closed(self, candle: Candle) -> float | None:
        """Returns the volume-median value as it stood *before* this candle (the
        gate semantics: "median of the prior 30 completed bars"), then updates
        state for the next call."""
        state = self._get_or_create(candle.symbol)
        median_before = state.volume_median_30.median()
        state.ema_fast_1m.update(candle.close)
        state.ema_slow_1m.update(candle.close)
        state.atr_1m.update(candle.high, candle.low, candle.close)
        state.volume_median_30.update(candle.quote_volume)
        state.last_kline_1m_close_time = candle.close_time
        state.last_candle_1m = candle
        state.candles_1m.append(candle)
        self.staleness.record(candle.symbol, Feed.KLINE_1M, candle.close_time)
        return median_before

    def on_kline_5m_closed(self, candle: Candle) -> None:
        state = self._get_or_create(candle.symbol)
        state.ema_fast_5m.update(candle.close)
        state.ema_slow_5m.update(candle.close)
        state.last_kline_5m_close_time = candle.close_time

    def get(self, symbol: str) -> SymbolState | None:
        return self._states.get(symbol)

    def symbols(self) -> list[str]:
        return list(self._states)
