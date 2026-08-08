"""Read-only endpoints under /api/v1 — SCANNER_DASHBOARD_PLAN.md §I / PLAN §6a.

Backed by real persisted data (signals, rejections, trades, meta) for P10 scope.
`/account`, `/positions`, `/orders`, `/fills`, `/equity`, `/risk` are listed in
PLAN §6a but their backing tables (live positions/orders/fills, running equity)
are populated by the trading loop, which is not wired up yet at this phase — they
return the correct shape with empty/zero data rather than fabricating numbers.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scalping.api.deps import AppState, get_session, get_state
from scalping.persistence.models import RejectionRow, SignalRow, TradeRow

router = APIRouter(prefix="/api/v1", tags=["read"])


@router.get("/signals")
async def list_signals(session: AsyncSession = Depends(get_session), limit: int = 100):
    stmt = select(SignalRow).order_by(SignalRow.id.desc()).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "symbol": r.symbol, "side": r.side, "strategy_version": r.strategy_version,
            "signal_time": r.signal_time.isoformat(), "strength": r.strength,
            "config_hash": r.config_hash,
        }
        for r in rows
    ]


@router.get("/rejections")
async def list_rejections(session: AsyncSession = Depends(get_session), limit: int = 100):
    stmt = select(RejectionRow).order_by(RejectionRow.id.desc()).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "symbol": r.symbol, "side": r.side, "reason": r.reason,
            "evaluated_at": r.evaluated_at.isoformat(), "strength": r.strength,
        }
        for r in rows
    ]


@router.get("/trades")
async def list_trades(session: AsyncSession = Depends(get_session), limit: int = 100):
    stmt = select(TradeRow).order_by(TradeRow.id.desc()).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "trade_id": r.trade_id, "symbol": r.symbol, "side": r.side,
            "r_multiple": r.r_multiple, "exit_reason": r.exit_reason,
            "opened_at": r.opened_at.isoformat(), "closed_at": r.closed_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/meta")
async def meta(state: AppState = Depends(get_state)):
    return {
        "environment": state.settings.environment,
        "strategy_version": state.settings.defaults.frozen.strategy_version,
        "config_hash": state.settings.defaults.config_hash(),
    }


@router.get("/account")
async def account():
    return {"equity": None, "note": "populated once the trading loop is wired to this API"}


@router.get("/positions")
async def positions():
    return []


@router.get("/orders")
async def orders():
    return []


@router.get("/fills")
async def fills():
    return []


@router.get("/equity")
async def equity():
    return {"curve": [], "note": "populated once the trading loop is wired to this API"}


@router.get("/risk")
async def risk():
    return {"daily_r": None, "weekly_r": None, "open_positions": 0}
