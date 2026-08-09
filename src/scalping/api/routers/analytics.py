"""Analytics + enriched trades API — S9."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scalping.accounting.journal import group_analytics
from scalping.api.deps import get_session
from scalping.persistence.models import TradeRow

router = APIRouter(prefix="/api/v1", tags=["analytics"])


def _trade_dict(r: TradeRow) -> dict[str, Any]:
    return {
        "trade_id": r.trade_id,
        "symbol": r.symbol,
        "side": r.side,
        "strategy_version": r.strategy_version,
        "r_multiple": r.r_multiple,
        "mae": r.mae,
        "mfe": r.mfe,
        "mae_r": r.mae,
        "mfe_r": r.mfe,
        "score_at_exit": r.score_at_exit,
        "cost_breakdown": r.cost_breakdown,
        "exit_reason": r.exit_reason,
        "opened_at": r.opened_at,
        "closed_at": r.closed_at,
        "regime": None,  # populated when signal→trade join lands; honest null for now
        "session": None,
    }


@router.get("/analytics")
async def analytics(
    group_by: str = Query("symbol"),
    session: AsyncSession = Depends(get_session),
    limit: int = 500,
):
    try:
        stmt = select(TradeRow).order_by(TradeRow.id.desc()).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        groups = group_analytics([_trade_dict(r) for r in rows], group_by=group_by)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "group_by": group_by,
        "n_trades": len(rows),
        "groups": [
            {
                "key": g.key,
                "n": g.n,
                "wins": g.wins,
                "sum_r": g.sum_r,
                "avg_r": g.avg_r,
                "win_rate": g.win_rate,
                "avg_mae": g.avg_mae,
                "avg_mfe": g.avg_mfe,
                "profit_factor": g.profit_factor if g.profit_factor != float("inf") else None,
                "profit_factor_infinite": g.profit_factor == float("inf"),
            }
            for g in groups
        ],
    }
