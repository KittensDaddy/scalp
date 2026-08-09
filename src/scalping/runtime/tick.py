"""Production evaluation tick — multi-strategy + per-symbol CAEMS presets."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scalping.api.broadcast import Broadcaster
from scalping.api.routers.developing import serialize_developing_setup
from scalping.api.routers.positions import serialize_active_trade
from scalping.api.routers.scanner import serialize_scanner_row
from scalping.config.class_resolver import (
    SymbolClassResolver,
    SymbolFacts,
    volume_ranks_from_tickers,
)
from scalping.config.frozen import FrozenParams
from scalping.config.presets import ClassPreset, load_presets_yaml
from scalping.config.settings import EffectiveConfig
from scalping.domain.models import SignalCandidate
from scalping.market_data.registry import SymbolStateRegistry
from scalping.monitoring.active_trades import ActiveTradeService
from scalping.risk.kill_switch import KillSwitch
from scalping.runtime.context import build_eval_context, build_snapshot
from scalping.runtime.paper_executor import PaperExecutor
from scalping.scanner.developing import DevelopingSetupsService
from scalping.scanner.runner import RunnerPassResult, StrategyRunner, SymbolEvalContext
from scalping.scanner.service import ScannerService

log = logging.getLogger(__name__)

OnSignals = Callable[[list[SignalCandidate], datetime], Awaitable[None] | None]


@dataclass
class ProductionTick:
    """One `on_tick` implementation shared by `--run` and tests."""

    registry: SymbolStateRegistry
    runner: StrategyRunner
    scanner: ScannerService
    developing: DevelopingSetupsService
    active_trades: ActiveTradeService
    broadcaster: Broadcaster
    kill_switch: KillSwitch
    config: EffectiveConfig
    symbols: list[str] = field(default_factory=list)
    frozen: FrozenParams = field(default_factory=FrozenParams)
    on_signals: OnSignals | None = None
    paper_executor: PaperExecutor | None = None
    execute: bool = True
    class_resolver: SymbolClassResolver | None = None
    volume_rank_by_symbol: dict[str, int] = field(default_factory=dict)
    # symbol → EffectiveConfig for paper sizing
    config_by_symbol: dict[str, EffectiveConfig] = field(default_factory=dict)

    async def __call__(self, supervisor: Any, now: datetime) -> RunnerPassResult:
        return await self.run(now)

    def update_volume_ranks(self, tickers: list[dict]) -> None:
        self.volume_rank_by_symbol = volume_ranks_from_tickers(tickers)

    async def run(self, now: datetime | None = None) -> RunnerPassResult:
        now = now or datetime.now(UTC)
        if self.paper_executor is not None:
            for symbol in self.symbols or self.registry.symbols():
                state = self.registry.get(symbol)
                if state is not None and state.last_book_ticker is not None:
                    self.paper_executor.venue.on_book_ticker(state.last_book_ticker)
            await self.paper_executor.sync_closes(now)

        btc_state = self.registry.get("BTCUSDT")
        btc_strength = None
        btc_fast = btc_slow = None
        btc_snapshot = None
        if btc_state is not None:
            btc_snapshot = build_snapshot(btc_state, now=now)
            if (
                btc_state.ema_fast_1m.ready
                and btc_state.ema_slow_1m.ready
                and btc_state.atr_1m.ready
                and btc_state.atr_1m.value
            ):
                btc_strength = (
                    btc_state.ema_fast_1m.value - btc_state.ema_slow_1m.value
                ) / btc_state.atr_1m.value
                btc_fast = btc_state.ema_fast_1m.value
                btc_slow = btc_state.ema_slow_1m.value

        contexts: list[SymbolEvalContext] = []
        self.config_by_symbol.clear()
        symbols = self.symbols or self.registry.symbols()
        for symbol in symbols:
            state = self.registry.get(symbol)
            if state is None:
                continue

            class_name = "btc" if symbol == "BTCUSDT" else "alt"
            cfg = self.config
            preset_name: str | None = None
            if self.class_resolver is not None:
                facts = SymbolFacts(
                    symbol=symbol,
                    quote_volume_rank=self.volume_rank_by_symbol.get(symbol),
                )
                resolved = self.class_resolver.resolve(facts)
                class_name = resolved.class_name
                cfg = resolved.config
                preset_name = resolved.class_name

            self.config_by_symbol[symbol] = cfg
            if self.paper_executor is not None:
                self.paper_executor.config_by_symbol[symbol] = cfg

            ctx = build_eval_context(
                state,
                config=cfg,
                evaluated_at=now,
                kill_switch=self.kill_switch,
                symbol_class=class_name,
                btc_strength=btc_strength if symbol != "BTCUSDT" else None,
                btc_ema_fast_1m=btc_fast,
                btc_ema_slow_1m=btc_slow,
                risk_approved=True,
            )
            if ctx is None:
                continue
            contexts.append(
                SymbolEvalContext(
                    symbol=ctx.symbol,
                    symbol_class=class_name,
                    state=ctx.state,
                    snapshot=ctx.snapshot,
                    feature_raw_by_side=ctx.feature_raw_by_side,
                    flags=ctx.flags,
                    risk_cost_by_side=ctx.risk_cost_by_side,
                    config=cfg,
                    config_hash=cfg.config_hash(),
                    preset=preset_name,
                )
            )

        if btc_state is not None:
            btc_closes = [c.close for c in btc_state.candles_1m]
            for plugin in self.runner.strategies:
                seed = getattr(plugin, "seed_btc_closes", None)
                if callable(seed) and btc_closes:
                    seed(btc_closes)

        result = self.runner.run_once(
            contexts,
            config=self.config,
            frozen=self.frozen,
            config_hash=self.config.config_hash(),
            evaluated_at=now,
            btc_snapshot=btc_snapshot,
        )
        await self._publish_feeds(now)
        self._mark_open_positions(now)

        # Drop CAEMS observe_only / disabled from executable signals.
        # Microstructure strategies may still trade those classes under their own rules.
        executable = []
        for s in result.signals:
            cfg = self.config_by_symbol.get(s.symbol, self.config)
            if s.strategy_version == "caems_v2" and (
                cfg.symbol_meta.observe_only or cfg.symbol_meta.disabled
            ):
                continue
            executable.append(s)

        handler = self.on_signals
        scores = {
            r.symbol: r.score
            for r in self.scanner.snapshot().rows
            if r.accepted
        }
        if handler is None and self.paper_executor is not None:
            async def _paper(signals, now, scores=scores):
                await self.paper_executor.on_signals(signals, now, scores=scores)

            handler = _paper
        if self.execute and handler is not None and executable:
            maybe = handler(executable, now)
            if maybe is not None:
                await maybe
        return result

    async def _publish_feeds(self, now: datetime) -> None:
        snap_s = self.scanner.snapshot()
        await self.broadcaster.publish(
            "scanner",
            {
                "type": "snapshot",
                "seq": snap_s.seq,
                "rows": [
                    serialize_scanner_row(r, self.registry.get(r.symbol), now=now)
                    for r in snap_s.rows
                ],
            },
        )
        snap_d = self.developing.snapshot()
        await self.broadcaster.publish(
            "developing",
            {
                "type": "snapshot",
                "seq": snap_d.seq,
                "setups": [serialize_developing_setup(s) for s in snap_d.setups],
            },
        )
        snap_p = self.active_trades.snapshot()
        await self.broadcaster.publish(
            "positions",
            {
                "type": "snapshot",
                "seq": snap_p.seq,
                "positions": [serialize_active_trade(t) for t in snap_p.positions],
            },
        )

    def _mark_open_positions(self, now: datetime) -> None:
        for trade in list(self.active_trades.snapshot().positions):
            state = self.registry.get(trade.symbol)
            if state is None:
                continue
            price = None
            if state.last_book_ticker is not None:
                price = state.last_book_ticker.mid
            elif state.last_candle_1m is not None:
                price = state.last_candle_1m.close
            if price is not None:
                self.active_trades.update_price(trade.trade_id, price)


def load_caems_presets(path: str | Path | None = None) -> dict[str, ClassPreset]:
    p = Path(path) if path else Path(__file__).resolve().parents[3] / "DOCS" / "caems_presets.yaml"
    return load_presets_yaml(p)
