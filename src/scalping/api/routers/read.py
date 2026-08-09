"""Read-only endpoints under /api/v1 — SCANNER_DASHBOARD_PLAN.md §I / PLAN §6a.

Backed by real persisted data (signals, rejections, trades, meta) for P10 scope.
`/account`, `/orders`, `/fills`, `/equity` still await the trading-loop wiring and
return empty/null shapes. `/positions` moved to `routers/positions.py` (S8).
`/risk.open_positions` is live off `ActiveTradeService`.
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
            "strategy_version": r.strategy_version,
            "r_multiple": r.r_multiple, "exit_reason": r.exit_reason,
            "opened_at": r.opened_at.isoformat(), "closed_at": r.closed_at.isoformat(),
            "mae": r.mae, "mfe": r.mfe, "score_at_exit": r.score_at_exit,
            "cost_breakdown": r.cost_breakdown,
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
async def risk(state: AppState = Depends(get_state)):
    open_n = len(state.active_trades.snapshot().positions)
    return {"daily_r": None, "weekly_r": None, "open_positions": open_n}


@router.get("/candles/{symbol}")
async def candles(
    symbol: str,
    state: AppState = Depends(get_state),
    interval: str = "1m",
    limit: int = 300,
):
    """Public kline proxy for the dashboard chart (avoids browser CORS on Binance)."""
    from scalping.exchanges.base.rate_limiter import RateLimiter
    from scalping.exchanges.binance.rest import BinanceRestClient
    from scalping.exchanges.proxy import choose_proxy, parse_proxy_list

    limit = max(1, min(limit, 1000))
    allowed = {"1m", "3m", "5m", "15m", "1h"}
    if interval not in allowed:
        interval = "1m"
    proxy = choose_proxy(
        parse_proxy_list(state.settings.http_proxy, state.settings.http_proxies),
        sticky="scalping-run",
    )
    rest = BinanceRestClient(
        base_url=state.settings.binance_rest_base,
        api_key=state.settings.binance_api_key,
        api_secret=state.settings.binance_api_secret,
        rate_limiter=RateLimiter(),
        proxy=proxy,
    )
    try:
        raw = await rest.klines(symbol=symbol.upper(), interval=interval, limit=limit)
    finally:
        await rest.aclose()
    return [
        {
            "time": int(r[0]) // 1000,
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
        }
        for r in raw
    ]
