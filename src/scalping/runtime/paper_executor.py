"""Paper execution path — same ExchangePort pipeline as testnet/live.

Runs entry_flow + protection off the event loop (create_task) so the eval tick
never blocks on maker TTL. Closes ActiveTradeService cards when the paper venue
drops the position (stop/TP hit). Persists closed trades + calibration samples
when a sessionmaker is injected.

Two campaign-evidence duties ride along with execution, because this is the only
place that knows a fill happened:

- **Markouts.** After each fill, mid at +5 s / +30 s is sampled and written back
  to the entry attempt. Without them the pre-registered maker/taker rule
  (`accounting/markouts.py`) has no data and PLAN §8 criterion 6 stays open
  forever.
- **Cooldowns.** `StrategyRunner` checks them; nothing else sets them. A closed
  trade puts its symbol on ice, longer after a loss.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker

from scalping.accounting.journal import CostBreakdown
from scalping.accounting.markouts import markout_bps, markout_r
from scalping.config.settings import EffectiveConfig
from scalping.domain.models import EntryOutcome, Position, Side, SignalCandidate, TradeEvent
from scalping.execution.client_order_id import make_client_algo_id, make_client_order_id
from scalping.execution.entry_flow import run_entry_flow
from scalping.execution.protection import establish_protection
from scalping.monitoring.active_trades import ActiveTrade, ActiveTradeService
from scalping.paper.venue import PaperVenue
from scalping.persistence.cooldown_repo import save_cooldown
from scalping.persistence.trade_events_repo import save_trade_event
from scalping.persistence.trades_repo import (
    record_calibration_sample,
    save_closed_trade,
    save_entry_attempt,
    update_entry_attempt_markouts,
)
from scalping.risk.engine import RiskEngine, RiskRequest
from scalping.scanner.cooldowns import Cooldown, CooldownManager

log = logging.getLogger(__name__)


def _default_regime(_symbol: str) -> str:
    return "unknown"


def _estimate_cost_r(
    *,
    entry: float,
    stop: float,
    config: EffectiveConfig,
    spread_bps: float,
) -> CostBreakdown:
    risk = abs(entry - stop)
    if risk <= 0 or entry <= 0:
        return CostBreakdown(fees_r=0.0, spread_r=0.0, slippage_r=0.0)
    fee_bps = config.cost.maker_fee_bps + config.cost.taker_fee_bps
    fees_r = (fee_bps / 10_000.0 * entry) / risk
    spread_r = (spread_bps / 10_000.0 * entry) / risk
    slip_r = (config.cost.safety_buffer_bps / 10_000.0 * entry) / risk
    return CostBreakdown(fees_r=fees_r, spread_r=spread_r, slippage_r=slip_r)


@dataclass
class PaperExecutor:
    venue: PaperVenue
    active_trades: ActiveTradeService
    config: EffectiveConfig
    risk: RiskEngine = field(default_factory=RiskEngine)
    equity: float = 10_000.0
    # strategy-caems.md §Order flow step 2. A sub-second TTL cannot produce a
    # maker fill: the order is queried back before the book has had a chance to
    # move through it, so every attempt converts to taker or is abandoned.
    entry_ttl_s: float = 3.0
    sessionmaker: async_sessionmaker | None = None
    config_hash: str = ""
    regime_for: Callable[[str], str] = field(default=_default_regime)
    # Shared with StrategyRunner so what we set here is what the scanner checks.
    cooldowns: CooldownManager | None = None
    markout_short_s: float = 5.0
    markout_long_s: float = 30.0
    # Injectable so markout tests don't wait 30 real seconds.
    sleep: Callable[[float], Any] = field(default=asyncio.sleep)
    # Per-symbol EffectiveConfig from CAEMS class presets (falls back to `config`).
    config_by_symbol: dict[str, EffectiveConfig] = field(default_factory=dict)
    _inflight: set[str] = field(default_factory=set)
    _symbol_to_trade: dict[str, str] = field(default_factory=dict)
    _tasks: list[asyncio.Task] = field(default_factory=list)
    _scores: dict[str, float] = field(default_factory=dict)
    _spreads: dict[str, float] = field(default_factory=dict)

    def _cfg(self, symbol: str) -> EffectiveConfig:
        return self.config_by_symbol.get(symbol, self.config)

    async def on_signals(
        self,
        signals: list[SignalCandidate],
        now: datetime,
        *,
        scores: dict[str, float] | None = None,
    ) -> None:
        if scores:
            self._scores.update(scores)
        for signal in signals:
            if signal.symbol in self._inflight or signal.symbol in self._symbol_to_trade:
                continue
            open_n = len(self.active_trades.snapshot().positions)
            if open_n >= self.config.risk.max_positions_total:
                continue
            self._inflight.add(signal.symbol)
            self._track(asyncio.create_task(self._enter(signal, now)))

    def _track(self, task: asyncio.Task) -> asyncio.Task:
        self._tasks.append(task)
        task.add_done_callback(self._on_task_done)
        return task

    async def aclose(self) -> None:
        """Cancel in-flight entry and markout tasks (shutdown)."""
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    def _on_task_done(self, task: asyncio.Task) -> None:
        with contextlib.suppress(ValueError):
            self._tasks.remove(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            log.exception("paper entry task failed: %s", exc)

    async def _enter(self, signal: SignalCandidate, now: datetime) -> None:
        try:
            cfg = self._cfg(signal.symbol)
            stop_distance = abs(signal.entry_reference - signal.stop)
            if stop_distance <= 0 or signal.entry_reference <= 0:
                return
            if cfg.symbol_meta.disabled or cfg.symbol_meta.observe_only:
                return
            open_n = len(self.active_trades.snapshot().positions)
            if open_n >= cfg.risk.max_positions_total:
                return
            approval = self.risk.evaluate(
                RiskRequest(
                    symbol=signal.symbol,
                    symbol_class="btc" if signal.symbol == "BTCUSDT" else "alt",
                    side=signal.side,
                    entry=signal.entry_reference,
                    stop=signal.stop,
                    equity=self.equity,
                    available_depth=self.equity,
                    bar_volume=self.equity,
                    exchange_max_notional=self.equity * 10,
                ),
                cfg.risk,
            )
            if not approval.approved or not approval.size:
                return
            qty = approval.size / signal.entry_reference
            if qty <= 0:
                return

            cid = make_client_order_id(
                strategy_version=signal.strategy_version,
                symbol=signal.symbol,
                side=signal.side,
                signal_time=signal.signal_time,
            )
            bt = self.venue.last_book(signal.symbol)
            if bt is not None:
                price = bt.bid_price if signal.side is Side.LONG else bt.ask_price
            else:
                price = signal.entry_reference

            edge_bps = (
                abs(signal.take_profit - signal.entry_reference) / signal.entry_reference
            ) * 10_000.0
            spread_bps = bt.spread_bps if bt is not None else 1.0
            self._spreads[signal.symbol] = spread_bps

            result = await run_entry_flow(
                port=self.venue,
                symbol=signal.symbol,
                side=signal.side,
                price=price,
                quantity=qty,
                client_order_id=cid,
                ttl_s=self.entry_ttl_s,
                cost_cfg=cfg.cost,
                spread_bps=spread_bps,
                remaining_edge_bps=edge_bps,
                now=now,
            )
            outcome = (
                result.outcome.value
                if isinstance(result.outcome, EntryOutcome)
                else str(result.outcome)
            )
            attempt_id = await self._persist_entry_attempt(
                symbol=signal.symbol,
                side=signal.side.value,
                outcome=outcome,
                attempted_at=now,
                fill_price=result.avg_fill_price,
                fill_time=result.fill_time,
            )
            if result.filled_quantity <= 0 or result.avg_fill_price is None:
                log.info("paper entry abandoned %s %s", signal.symbol, outcome)
                return

            fill_price = result.avg_fill_price
            if attempt_id is not None:
                self._track(
                    asyncio.create_task(
                        self._measure_markouts(
                            attempt_id=attempt_id,
                            symbol=signal.symbol,
                            side=signal.side,
                            fill_price=fill_price,
                            stop_distance=stop_distance,
                        )
                    )
                )
            trade_id = str(uuid4())
            score = self._scores.get(signal.symbol)
            position = Position(
                symbol=signal.symbol,
                side=signal.side,
                entry_price=fill_price,
                quantity=result.filled_quantity,
                stop_price=signal.stop,
                take_profit_price=signal.take_profit,
                opened_at=now,
                protected=False,
            )
            _trade, opened_event, _ = self.active_trades.open_trade(
                trade_id=trade_id,
                position=position,
                current_price=fill_price,
                score=score,
                strategy_version=signal.strategy_version,
                ts=now,
            )
            self._symbol_to_trade[signal.symbol] = trade_id
            self.risk.on_position_opened(
                "btc" if signal.symbol == "BTCUSDT" else "alt"
            )
            await self._persist_event(opened_event)

            try:
                prot = await establish_protection(
                    port=self.venue,
                    symbol=signal.symbol,
                    side=signal.side,
                    quantity=result.filled_quantity,
                    stop_price=signal.stop,
                    tp_price=signal.take_profit,
                    fill_time=now,
                    protection_timeout_ms=cfg.protection_timeout_ms,
                    client_algo_id_stop=make_client_algo_id(
                        purpose="stop",
                        strategy_version=signal.strategy_version,
                        symbol=signal.symbol,
                        side=signal.side,
                        signal_time=signal.signal_time,
                    ),
                    client_algo_id_tp=make_client_algo_id(
                        purpose="tp",
                        strategy_version=signal.strategy_version,
                        symbol=signal.symbol,
                        side=signal.side,
                        signal_time=signal.signal_time,
                    ),
                )
                _t, prot_event, _ = self.active_trades.mark_protected(
                    trade_id, ts=now, t_protection_ms=prot.t_protection_ms
                )
                await self._persist_event(prot_event)
            except Exception as exc:
                log.exception("paper protection failed %s: %s", signal.symbol, exc)
                await self.venue.place_reduce_only_market_close(
                    signal.symbol, signal.side, result.filled_quantity
                )
                closed, close_event, _ = self.active_trades.close_trade(
                    trade_id, exit_price=fill_price, exit_reason="PROTECTION_TIMEOUT", ts=now
                )
                self._symbol_to_trade.pop(signal.symbol, None)
                self.risk.on_position_closed(
                    "btc" if signal.symbol == "BTCUSDT" else "alt"
                )
                # A protection-timeout close is a real completed trade: it has to
                # reach the drawdown machine like any other, or the loss budget
                # silently ignores exactly the failures it exists to catch.
                self.risk.on_trade_closed(closed.unrealized_r)
                await self._apply_close_cooldown(signal.symbol, closed.unrealized_r, now)
                await self._persist_event(close_event)
                await self._persist_closed(closed)
                return

            log.info(
                "paper opened %s %s qty=%.6f outcome=%s",
                signal.symbol,
                signal.side.value,
                result.filled_quantity,
                outcome,
            )
        finally:
            self._inflight.discard(signal.symbol)

    async def _measure_markouts(
        self,
        *,
        attempt_id: int,
        symbol: str,
        side: Side,
        fill_price: float,
        stop_distance: float,
    ) -> None:
        """Sample mid at +5 s and +30 s after the fill and write both back.

        Each offset is persisted as soon as it is measured, so a restart between
        the two leaves a real 5 s reading rather than discarding both.
        """
        offsets = (
            (self.markout_short_s, "5s"),
            (self.markout_long_s - self.markout_short_s, "30s"),
        )
        for delay, label in offsets:
            if delay > 0:
                await self.sleep(delay)
            bt = self.venue.last_book(symbol)
            if bt is None:
                continue
            bps = markout_bps(fill_price=fill_price, mid_at_offset=bt.mid, side=side)
            r = (
                markout_r(
                    markout_bps_value=bps, fill_price=fill_price, stop_distance=stop_distance
                )
                if stop_distance > 0
                else None
            )
            await self._persist_markout(attempt_id, label=label, bps=bps, r=r)

    async def _persist_markout(
        self, attempt_id: int, *, label: str, bps: float, r: float | None
    ) -> None:
        if self.sessionmaker is None:
            return
        fields: dict[str, float] = {f"markout_{label}_bps": bps}
        if r is not None:
            fields[f"markout_{label}_r"] = r
        try:
            async with self.sessionmaker() as session:
                await update_entry_attempt_markouts(session, attempt_id=attempt_id, **fields)
                await session.commit()
        except Exception:
            log.exception("failed to persist %s markout for attempt %s", label, attempt_id)

    async def _apply_close_cooldown(self, symbol: str, r_multiple: float, now: datetime) -> None:
        """Cool a symbol down after a completed trade — longer after a loss."""
        if self.cooldowns is None:
            return
        cfg = self._cfg(symbol)
        lost = r_multiple <= 0
        seconds = cfg.cooldowns.post_loss_s if lost else cfg.cooldowns.post_trade_s
        if seconds <= 0:
            return
        reason = "post_loss" if lost else "post_trade"
        until = now + timedelta(seconds=seconds)
        self.cooldowns.set("symbol", symbol, reason, until)
        if self.sessionmaker is None:
            return
        try:
            async with self.sessionmaker() as session:
                await save_cooldown(session, Cooldown("symbol", symbol, reason, until))
                await session.commit()
        except Exception:
            log.exception("failed to persist cooldown for %s", symbol)

    async def sync_closes(self, now: datetime) -> None:
        """Close ActiveTrade cards when PaperVenue no longer holds the position."""
        open_syms = {p.symbol for p in await self.venue.get_open_positions()}
        for symbol, trade_id in list(self._symbol_to_trade.items()):
            if symbol in open_syms:
                continue
            trade = self.active_trades.get(trade_id)
            if trade is None or trade.closed:
                self._symbol_to_trade.pop(symbol, None)
                continue
            # Price the exit where the venue actually filled it. Falling back to
            # the last mark only happens if the venue lost the record, and it
            # biases R by however stale that mark is.
            fill = self.venue.take_close_fill(symbol)
            closed, close_event, _ = self.active_trades.close_trade(
                trade_id,
                exit_price=fill.price if fill is not None else trade.current_price,
                exit_reason=fill.reason if fill is not None else "STOP_OR_TP",
                ts=now,
            )
            self._symbol_to_trade.pop(symbol, None)
            self.risk.on_position_closed(
                "btc" if symbol == "BTCUSDT" else "alt"
            )
            self.risk.on_trade_closed(closed.unrealized_r)
            await self._apply_close_cooldown(symbol, closed.unrealized_r, now)
            await self._persist_event(close_event)
            await self._persist_closed(closed)

    async def _persist_event(self, event: TradeEvent | None) -> None:
        if event is None or self.sessionmaker is None:
            return
        try:
            async with self.sessionmaker() as session:
                await save_trade_event(session, event)
                await session.commit()
        except Exception:
            log.exception("failed to persist trade event %s", event.event_type)

    async def _persist_entry_attempt(self, **kwargs: Any) -> int | None:
        """Returns the attempt's row id so markouts can be written back to it."""
        if self.sessionmaker is None:
            return None
        try:
            async with self.sessionmaker() as session:
                row = await save_entry_attempt(
                    session, config_hash=self.config_hash or "unknown", **kwargs
                )
                attempt_id = row.id
                await session.commit()
                return attempt_id
        except Exception:
            log.exception("failed to persist entry attempt")
            return None

    async def _persist_closed(self, trade: ActiveTrade) -> None:
        if self.sessionmaker is None:
            return
        try:
            cost = _estimate_cost_r(
                entry=trade.entry_price,
                stop=trade.initial_stop_price,
                config=self._cfg(trade.symbol),
                spread_bps=self._spreads.get(trade.symbol, 1.0),
            )
            regime = self.regime_for(trade.symbol)
            async with self.sessionmaker() as session:
                await save_closed_trade(
                    session,
                    trade=trade,
                    config_hash=self.config_hash or "unknown",
                    cost=cost,
                    regime=regime,
                )
                await record_calibration_sample(
                    session,
                    strategy_version=trade.strategy_version,
                    side=trade.side.value,
                    regime=regime,
                    score=trade.score,
                    r_multiple=trade.unrealized_r,
                    updated_at=trade.closed_at or datetime.now(),
                )
                await session.commit()
            log.info(
                "paper closed+persisted %s r=%.3f reason=%s",
                trade.symbol,
                trade.unrealized_r,
                trade.exit_reason,
            )
        except Exception:
            log.exception("failed to persist closed trade %s", trade.trade_id)
