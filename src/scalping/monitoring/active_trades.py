"""Active-trade monitoring + lifecycle timeline — SCANNER_DASHBOARD_PLAN.md §S8.

Pure geometry helpers (`update_mae_mfe`, `classify_health`, distances in R) plus
`ActiveTradeService`, which mirrors `ScannerService`/`DevelopingSetupsService`'s
seq-numbered snapshot/publish shape so `/stream/positions` can reuse the same
client pattern.

Hard constraint (spec): qualitative `HealthLabel` only — percentages and
win-probabilities are rejected in code, not just omitted from the UI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime

from scalping.domain.models import (
    HealthLabel,
    Position,
    Side,
    TradeEvent,
    TradeEventType,
)

# Keys that look like pre-calibration probabilities. Matched case-insensitively
# against every payload / serialized field name.
_PROBABILITY_KEY_RE = re.compile(
    r"(probabilit|win[_]?rate|chance|pct_win|p_win|win_pct|success_rate)",
    re.IGNORECASE,
)

# Fraction of initial R remaining to stop/TP that triggers NEAR_* labels.
_NEAR_THRESHOLD_R = 0.25


def reject_probability_fields(data: dict) -> None:
    """Raise if any key looks like a probability — S8 must not invent them."""
    for key in data:
        if _PROBABILITY_KEY_RE.search(str(key)):
            raise ValueError(
                f"probability field '{key}' is forbidden until S10 calibration"
            )


def risk_distance(entry_price: float, stop_price: float) -> float:
    return abs(entry_price - stop_price)


def unrealized_r(
    *, side: Side, entry_price: float, stop_price: float, price: float
) -> float:
    rd = risk_distance(entry_price, stop_price)
    if rd == 0:
        return 0.0
    if side is Side.LONG:
        return (price - entry_price) / rd
    return (entry_price - price) / rd


def distance_to_stop_r(
    *, side: Side, stop_price: float, price: float, initial_risk: float
) -> float:
    """R remaining before stop is hit (positive = still room), scaled by initial risk."""
    if initial_risk == 0:
        return 0.0
    if side is Side.LONG:
        return (price - stop_price) / initial_risk
    return (stop_price - price) / initial_risk


def distance_to_tp_r(
    *,
    side: Side,
    take_profit_price: float,
    price: float,
    initial_risk: float,
) -> float:
    """R remaining before TP is hit (positive = still room), scaled by initial risk."""
    if initial_risk == 0:
        return 0.0
    if side is Side.LONG:
        return (take_profit_price - price) / initial_risk
    return (price - take_profit_price) / initial_risk


def update_mae_mfe(mae_r: float, mfe_r: float, unrealized: float) -> tuple[float, float]:
    """Side-effect-free MAE/MFE update. Both stored as non-negative R magnitudes
    (MAE = worst adverse excursion, MFE = best favorable excursion)."""
    new_mae = max(mae_r, max(0.0, -unrealized))
    new_mfe = max(mfe_r, max(0.0, unrealized))
    return new_mae, new_mfe


def classify_health(
    *,
    distance_to_stop: float,
    distance_to_tp: float,
    unrealized: float,
    near_threshold_r: float = _NEAR_THRESHOLD_R,
) -> HealthLabel:
    """Deterministic geometry → qualitative label. Never a probability."""
    if distance_to_stop <= near_threshold_r:
        return HealthLabel.NEAR_STOP
    if distance_to_tp <= near_threshold_r:
        return HealthLabel.NEAR_TP
    if unrealized < 0:
        return HealthLabel.AT_RISK
    return HealthLabel.HEALTHY


@dataclass(frozen=True)
class ActiveTrade:
    trade_id: str
    symbol: str
    side: Side
    entry_price: float
    quantity: float
    stop_price: float
    take_profit_price: float
    opened_at: datetime
    current_price: float
    unrealized_r: float
    mae_r: float
    mfe_r: float
    distance_to_stop_r: float
    distance_to_tp_r: float
    health: HealthLabel
    initial_stop_price: float
    protected: bool = False
    breakeven_moved: bool = False
    score: float | None = None
    strategy_version: str = "caems_v2"
    closed: bool = False
    exit_reason: str | None = None
    closed_at: datetime | None = None


@dataclass(frozen=True)
class ActiveTradesSnapshot:
    seq: int
    positions: list[ActiveTrade]


def _metrics_from_price(
    *,
    side: Side,
    entry_price: float,
    initial_stop_price: float,
    stop_price: float,
    take_profit_price: float,
    price: float,
    mae_r: float,
    mfe_r: float,
) -> tuple[float, float, float, float, float, HealthLabel]:
    # Unrealized / MAE / MFE are always vs initial risk so a BE move doesn't
    # redefine R mid-trade. Distances use the live stop/TP, scaled by initial R.
    initial_risk = risk_distance(entry_price, initial_stop_price)
    ur = unrealized_r(
        side=side, entry_price=entry_price, stop_price=initial_stop_price, price=price
    )
    mae, mfe = update_mae_mfe(mae_r, mfe_r, ur)
    d_stop = distance_to_stop_r(
        side=side, stop_price=stop_price, price=price, initial_risk=initial_risk
    )
    d_tp = distance_to_tp_r(
        side=side,
        take_profit_price=take_profit_price,
        price=price,
        initial_risk=initial_risk,
    )
    health = classify_health(
        distance_to_stop=d_stop, distance_to_tp=d_tp, unrealized=ur
    )
    return ur, mae, mfe, d_stop, d_tp, health


def build_active_trade(
    *,
    trade_id: str,
    position: Position,
    current_price: float,
    strategy_version: str = "caems_v2",
    score: float | None = None,
    mae_r: float = 0.0,
    mfe_r: float = 0.0,
) -> ActiveTrade:
    ur, mae, mfe, d_stop, d_tp, health = _metrics_from_price(
        side=position.side,
        entry_price=position.entry_price,
        initial_stop_price=position.stop_price,
        stop_price=position.stop_price,
        take_profit_price=position.take_profit_price,
        price=current_price,
        mae_r=mae_r,
        mfe_r=mfe_r,
    )
    return ActiveTrade(
        trade_id=trade_id,
        symbol=position.symbol,
        side=position.side,
        entry_price=position.entry_price,
        quantity=position.quantity,
        stop_price=position.stop_price,
        take_profit_price=position.take_profit_price,
        opened_at=position.opened_at,
        current_price=current_price,
        unrealized_r=ur,
        mae_r=mae,
        mfe_r=mfe,
        distance_to_stop_r=d_stop,
        distance_to_tp_r=d_tp,
        health=health,
        initial_stop_price=position.stop_price,
        protected=position.protected,
        breakeven_moved=position.breakeven_moved,
        score=score,
        strategy_version=strategy_version,
    )


class ActiveTradeService:
    """In-memory open positions + per-trade event timelines, seq-published for WS."""

    def __init__(self) -> None:
        self._trades: dict[str, ActiveTrade] = {}
        self._events: dict[str, list[TradeEvent]] = {}
        self._seq = 0

    def _bump(self) -> ActiveTradesSnapshot:
        self._seq += 1
        return self.snapshot()

    def _append_event(self, event: TradeEvent) -> None:
        reject_probability_fields(event.payload)
        self._events.setdefault(event.trade_id, []).append(event)

    def snapshot(self) -> ActiveTradesSnapshot:
        open_positions = [t for t in self._trades.values() if not t.closed]
        ranked = sorted(open_positions, key=lambda t: t.opened_at)
        return ActiveTradesSnapshot(seq=self._seq, positions=ranked)

    def events(self, trade_id: str) -> list[TradeEvent]:
        return list(self._events.get(trade_id, []))

    def get(self, trade_id: str) -> ActiveTrade | None:
        return self._trades.get(trade_id)

    def open_trade(
        self,
        *,
        trade_id: str,
        position: Position,
        current_price: float | None = None,
        strategy_version: str = "caems_v2",
        score: float | None = None,
        ts: datetime | None = None,
    ) -> tuple[ActiveTrade, TradeEvent, ActiveTradesSnapshot]:
        if trade_id in self._trades and not self._trades[trade_id].closed:
            raise ValueError(f"trade {trade_id} is already open")
        price = current_price if current_price is not None else position.entry_price
        trade = build_active_trade(
            trade_id=trade_id,
            position=position,
            current_price=price,
            strategy_version=strategy_version,
            score=score,
        )
        event_ts = ts if ts is not None else position.opened_at
        event = TradeEvent(
            trade_id=trade_id,
            symbol=position.symbol,
            event_type=TradeEventType.OPENED,
            ts=event_ts,
            payload={
                "side": position.side.value,
                "entry_price": position.entry_price,
                "stop_price": position.stop_price,
                "take_profit_price": position.take_profit_price,
                "quantity": position.quantity,
                "score": score,
            },
        )
        self._trades[trade_id] = trade
        self._append_event(event)
        return trade, event, self._bump()

    def mark_protected(
        self, trade_id: str, *, ts: datetime, t_protection_ms: float | None = None
    ) -> tuple[ActiveTrade, TradeEvent, ActiveTradesSnapshot]:
        trade = self._require_open(trade_id)
        updated = replace(trade, protected=True)
        payload: dict = {}
        if t_protection_ms is not None:
            payload["t_protection_ms"] = t_protection_ms
        event = TradeEvent(
            trade_id=trade_id,
            symbol=trade.symbol,
            event_type=TradeEventType.PROTECTED,
            ts=ts,
            payload=payload,
        )
        self._trades[trade_id] = updated
        self._append_event(event)
        return updated, event, self._bump()

    def move_breakeven(
        self, trade_id: str, *, new_stop: float, ts: datetime
    ) -> tuple[ActiveTrade, TradeEvent, ActiveTradesSnapshot]:
        trade = self._require_open(trade_id)
        ur, mae, mfe, d_stop, d_tp, health = _metrics_from_price(
            side=trade.side,
            entry_price=trade.entry_price,
            initial_stop_price=trade.initial_stop_price,
            stop_price=new_stop,
            take_profit_price=trade.take_profit_price,
            price=trade.current_price,
            mae_r=trade.mae_r,
            mfe_r=trade.mfe_r,
        )
        updated = replace(
            trade,
            stop_price=new_stop,
            breakeven_moved=True,
            unrealized_r=ur,
            mae_r=mae,
            mfe_r=mfe,
            distance_to_stop_r=d_stop,
            distance_to_tp_r=d_tp,
            health=health,
        )
        event = TradeEvent(
            trade_id=trade_id,
            symbol=trade.symbol,
            event_type=TradeEventType.BREAKEVEN_MOVED,
            ts=ts,
            payload={"old_stop": trade.stop_price, "new_stop": new_stop},
        )
        self._trades[trade_id] = updated
        self._append_event(event)
        return updated, event, self._bump()

    def update_score(
        self,
        trade_id: str,
        *,
        score: float,
        ts: datetime,
        explanation: str | None = None,
    ) -> tuple[ActiveTrade, TradeEvent | None, ActiveTradesSnapshot]:
        """Records SCORE_CHANGED only when the value actually changes. Payload may
        carry a qualitative explanation string — never a probability."""
        trade = self._require_open(trade_id)
        if trade.score == score:
            return trade, None, self.snapshot()
        payload: dict = {"old_score": trade.score, "new_score": score}
        if explanation is not None:
            payload["explanation"] = explanation
        reject_probability_fields(payload)
        updated = replace(trade, score=score)
        event = TradeEvent(
            trade_id=trade_id,
            symbol=trade.symbol,
            event_type=TradeEventType.SCORE_CHANGED,
            ts=ts,
            payload=payload,
        )
        self._trades[trade_id] = updated
        self._append_event(event)
        return updated, event, self._bump()

    def update_price(
        self, trade_id: str, price: float
    ) -> tuple[ActiveTrade, ActiveTradesSnapshot]:
        """Live mark update — refreshes R/MAE/MFE/health and bumps seq, but does
        not append a TradeEvent (ticks would drown the timeline)."""
        trade = self._require_open(trade_id)
        ur, mae, mfe, d_stop, d_tp, health = _metrics_from_price(
            side=trade.side,
            entry_price=trade.entry_price,
            initial_stop_price=trade.initial_stop_price,
            stop_price=trade.stop_price,
            take_profit_price=trade.take_profit_price,
            price=price,
            mae_r=trade.mae_r,
            mfe_r=trade.mfe_r,
        )
        updated = replace(
            trade,
            current_price=price,
            unrealized_r=ur,
            mae_r=mae,
            mfe_r=mfe,
            distance_to_stop_r=d_stop,
            distance_to_tp_r=d_tp,
            health=health,
        )
        self._trades[trade_id] = updated
        return updated, self._bump()

    def close_trade(
        self,
        trade_id: str,
        *,
        exit_price: float,
        exit_reason: str,
        ts: datetime,
    ) -> tuple[ActiveTrade, TradeEvent, ActiveTradesSnapshot]:
        trade = self._require_open(trade_id)
        ur, mae, mfe, d_stop, d_tp, health = _metrics_from_price(
            side=trade.side,
            entry_price=trade.entry_price,
            initial_stop_price=trade.initial_stop_price,
            stop_price=trade.stop_price,
            take_profit_price=trade.take_profit_price,
            price=exit_price,
            mae_r=trade.mae_r,
            mfe_r=trade.mfe_r,
        )
        updated = replace(
            trade,
            current_price=exit_price,
            unrealized_r=ur,
            mae_r=mae,
            mfe_r=mfe,
            distance_to_stop_r=d_stop,
            distance_to_tp_r=d_tp,
            health=health,
            closed=True,
            exit_reason=exit_reason,
            closed_at=ts,
        )
        event = TradeEvent(
            trade_id=trade_id,
            symbol=trade.symbol,
            event_type=TradeEventType.CLOSED,
            ts=ts,
            payload={
                "exit_price": exit_price,
                "exit_reason": exit_reason,
                "r_multiple": ur,
                "mae_r": mae,
                "mfe_r": mfe,
            },
        )
        self._trades[trade_id] = updated
        self._append_event(event)
        return updated, event, self._bump()

    def _require_open(self, trade_id: str) -> ActiveTrade:
        trade = self._trades.get(trade_id)
        if trade is None:
            raise KeyError(f"unknown trade_id {trade_id}")
        if trade.closed:
            raise ValueError(f"trade {trade_id} is already closed")
        return trade
