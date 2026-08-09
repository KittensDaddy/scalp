"""Active-trade / positions API + WS feed — SCANNER_DASHBOARD_PLAN.md §S8.

`GET /positions` returns the seq-numbered open-position snapshot.
`GET /positions/{trade_id}/events` returns the lifecycle timeline.
`/stream/positions` sends a snapshot on connect then forwards broadcaster
"positions" channel messages (same shape as developing/scanner).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect

from scalping.api.deps import AppState, get_state
from scalping.domain.models import TradeEvent
from scalping.monitoring.active_trades import ActiveTrade, reject_probability_fields

router = APIRouter(prefix="/api/v1", tags=["positions"])


def serialize_active_trade(trade: ActiveTrade) -> dict[str, Any]:
    """Card payload: R / MAE / MFE / distances / HealthLabel — never a probability."""
    body = {
        "trade_id": trade.trade_id,
        "symbol": trade.symbol,
        "side": trade.side.value,
        "entry_price": trade.entry_price,
        "quantity": trade.quantity,
        "stop_price": trade.stop_price,
        "take_profit_price": trade.take_profit_price,
        "opened_at": trade.opened_at.isoformat(),
        "current_price": trade.current_price,
        "unrealized_r": trade.unrealized_r,
        "mae_r": trade.mae_r,
        "mfe_r": trade.mfe_r,
        "distance_to_stop_r": trade.distance_to_stop_r,
        "distance_to_tp_r": trade.distance_to_tp_r,
        "health": trade.health.value,
        "initial_stop_price": trade.initial_stop_price,
        "protected": trade.protected,
        "breakeven_moved": trade.breakeven_moved,
        "score": trade.score,
        "strategy_version": trade.strategy_version,
        "closed": trade.closed,
        "exit_reason": trade.exit_reason,
        "closed_at": trade.closed_at.isoformat() if trade.closed_at else None,
    }
    reject_probability_fields(body)
    return body


def serialize_trade_event(event: TradeEvent) -> dict[str, Any]:
    reject_probability_fields(event.payload)
    return {
        "trade_id": event.trade_id,
        "symbol": event.symbol,
        "event_type": event.event_type.value,
        "ts": event.ts.isoformat(),
        "payload": event.payload,
    }


def positions_snapshot_message(state: AppState) -> dict[str, Any]:
    snapshot = state.active_trades.snapshot()
    return {
        "type": "snapshot",
        "seq": snapshot.seq,
        "positions": [serialize_active_trade(t) for t in snapshot.positions],
    }


@router.get("/positions")
async def get_positions(state: AppState = Depends(get_state)):
    snapshot = state.active_trades.snapshot()
    return {
        "seq": snapshot.seq,
        "positions": [serialize_active_trade(t) for t in snapshot.positions],
    }


@router.get("/positions/{trade_id}/events")
async def get_position_events(trade_id: str, state: AppState = Depends(get_state)):
    if state.active_trades.get(trade_id) is None and not state.active_trades.events(trade_id):
        raise HTTPException(status_code=404, detail="trade not found")
    return {
        "trade_id": trade_id,
        "events": [serialize_trade_event(e) for e in state.active_trades.events(trade_id)],
    }


@router.websocket("/stream/positions")
async def stream_positions(websocket: WebSocket):
    await websocket.accept()
    state: AppState = websocket.app.state.scalping
    await websocket.send_json(positions_snapshot_message(state))

    queue = state.broadcaster.subscribe("positions")
    try:
        while True:
            delta = await queue.get()
            await websocket.send_json(delta)
    except WebSocketDisconnect:
        pass
    finally:
        state.broadcaster.unsubscribe("positions", queue)
