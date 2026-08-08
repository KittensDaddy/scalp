"""Developing Setups API + WS feed — SCANNER_DASHBOARD_PLAN.md §S7.

Mirrors `routers/scanner.py`'s shape (`GET` snapshot + `WS` deltas via the
broadcaster's "developing" channel) so the frontend can reuse the same
seq-gap-resnapshot client logic as the main scanner table.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from scalping.api.deps import AppState, get_state
from scalping.scanner.developing import DevelopingSetup

router = APIRouter(prefix="/api/v1", tags=["developing"])


def serialize_developing_setup(setup: DevelopingSetup) -> dict[str, Any]:
    return {
        "symbol": setup.symbol,
        "side": setup.side.value,
        "score": setup.score,
        "missing_conditions": setup.missing_conditions,
        "projections": setup.projections,
        "detected_at": setup.detected_at.isoformat(),
    }


@router.get("/developing")
async def get_developing(state: AppState = Depends(get_state)):
    snapshot = state.developing.snapshot()
    return {
        "seq": snapshot.seq,
        "setups": [serialize_developing_setup(s) for s in snapshot.setups],
    }


@router.websocket("/stream/developing")
async def stream_developing(websocket: WebSocket):
    await websocket.accept()
    state: AppState = websocket.app.state.scalping
    snapshot = state.developing.snapshot()
    await websocket.send_json({
        "type": "snapshot",
        "seq": snapshot.seq,
        "setups": [serialize_developing_setup(s) for s in snapshot.setups],
    })

    queue = state.broadcaster.subscribe("developing")
    try:
        while True:
            delta = await queue.get()
            await websocket.send_json(delta)
    except WebSocketDisconnect:
        pass
    finally:
        state.broadcaster.unsubscribe("developing", queue)
