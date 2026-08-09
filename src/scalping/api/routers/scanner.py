"""Scanner API + WS feed — SCANNER_DASHBOARD_PLAN.md §I.

Row schema fields not yet derivable from data this codebase produces (`vol_24h`,
`rr`, `net_edge_r`) are returned as `null` rather than fabricated — the same
honesty rule P10's `/positions`/`/orders` stubs follow. They populate once the
universe/cost-model wiring feeds the scanner (S1 already computes 24h volume
during universe building; wiring it through is a follow-up, not a schema change).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from scalping.api.deps import AppState, get_state
from scalping.market_data.registry import SymbolState
from scalping.scanner.service import ScannerRow

router = APIRouter(prefix="/api/v1", tags=["scanner"])


def serialize_scanner_row(
    row: ScannerRow, state: SymbolState | None, *, now: datetime
) -> dict[str, Any]:
    price = None
    spread_bps = None
    atr_pct = None
    age_ms = None

    if state is not None:
        if state.last_candle_1m is not None:
            price = state.last_candle_1m.close
        if state.last_book_ticker is not None:
            price = state.last_book_ticker.mid
            spread_bps = state.last_book_ticker.spread_bps
        if state.atr_1m.ready and price:
            atr_pct = state.atr_1m.value / price
        if state.last_kline_1m_close_time is not None:
            age_ms = (now - state.last_kline_1m_close_time).total_seconds() * 1000.0

    return {
        "symbol": row.symbol,
        "side": row.side.value,
        "score": row.score,
        "strategy": row.strategy,
        "preset": row.preset,
        "price": price,
        "spread_bps": spread_bps,
        "vol_24h": None,
        "atr_pct": atr_pct,
        "rr": None,
        "net_edge_r": None,
        "state": (
            "WARMING"
            if row.strategy == "warming"
            else ("ACCEPTED" if row.accepted else "REJECTED")
        ),
        "age_ms": age_ms,
        "reasons_top3": [row.rejection_reason.value] if row.rejection_reason else [],
    }


@router.get("/scanner")
async def get_scanner(state: AppState = Depends(get_state)):
    snapshot = state.scanner.snapshot()
    now = datetime.now(UTC)
    return {
        "seq": snapshot.seq,
        "rows": [
            serialize_scanner_row(r, state.registry.get(r.symbol), now=now) for r in snapshot.rows
        ],
    }


@router.get("/symbol/{symbol}")
async def get_symbol(symbol: str, state: AppState = Depends(get_state)):
    row = state.scanner.row(symbol)
    symbol_state = state.registry.get(symbol)
    now = datetime.now(UTC)

    breakdown = None
    why_not: list[str] = []
    if row is not None:
        if row.breakdown is not None:
            breakdown = {"total": row.breakdown.total, "components": row.breakdown.components}
        if row.rejection_reason is not None:
            why_not = [row.rejection_reason.value]

    return {
        "symbol": symbol,
        "row": serialize_scanner_row(row, symbol_state, now=now) if row is not None else None,
        "breakdown": breakdown,
        "why_not": why_not,
    }


@router.websocket("/stream/scanner")
async def stream_scanner(websocket: WebSocket):
    await websocket.accept()
    state: AppState = websocket.app.state.scalping
    snapshot = state.scanner.snapshot()
    now = datetime.now(UTC)
    await websocket.send_json({
        "type": "snapshot",
        "seq": snapshot.seq,
        "rows": [
            serialize_scanner_row(r, state.registry.get(r.symbol), now=now) for r in snapshot.rows
        ],
    })

    queue = state.broadcaster.subscribe("scanner")
    try:
        while True:
            delta = await queue.get()
            await websocket.send_json(delta)
    except WebSocketDisconnect:
        pass
    finally:
        state.broadcaster.unsubscribe("scanner", queue)


@router.websocket("/stream/system")
async def stream_system(websocket: WebSocket):
    await websocket.accept()
    state: AppState = websocket.app.state.scalping
    queue = state.broadcaster.subscribe("system")
    try:
        while True:
            msg = await queue.get()
            await websocket.send_json(msg)
    except WebSocketDisconnect:
        pass
    finally:
        state.broadcaster.unsubscribe("system", queue)
