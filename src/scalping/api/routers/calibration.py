"""Calibration API — S10. Probabilities only when n ≥ min_samples."""

from __future__ import annotations

from datetime import UTC

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scalping.api.deps import get_session
from scalping.edge.calibration import (
    CalibrationKey,
    CalibrationStats,
    gate_probability,
    wilson_ci,
)
from scalping.persistence.models import CalibrationStatsRow

router = APIRouter(prefix="/api/v1", tags=["calibration"])


@router.get("/calibration")
async def list_calibration(
    session: AsyncSession = Depends(get_session),
    min_samples: int = Query(30, ge=1),
):
    stmt = select(CalibrationStatsRow).order_by(CalibrationStatsRow.updated_at.desc())
    rows = (await session.execute(stmt)).scalars().all()
    out = []
    for r in rows:
        stats = CalibrationStats(
            key=CalibrationKey(
                strategy_version=r.strategy_version,
                side=r.side,
                regime=r.regime,
                score_bucket=r.score_bucket,
            ),
            n=r.n,
            wins=r.wins,
            sum_r=r.sum_r,
            updated_at=(
                r.updated_at.replace(tzinfo=UTC)
                if r.updated_at.tzinfo is None
                else r.updated_at
            ),
        )
        estimate = gate_probability(stats, min_samples=min_samples)
        # Prefer persisted CI when available and gate passes; else recompute.
        ci = wilson_ci(r.wins, r.n) if estimate.available else None
        out.append(
            {
                "strategy_version": r.strategy_version,
                "side": r.side,
                "regime": r.regime,
                "score_bucket": r.score_bucket,
                "n": r.n,
                "wins": r.wins,
                "sum_r": r.sum_r,
                "probability": {
                    "available": estimate.available,
                    "win_probability": estimate.win_probability if estimate.available else None,
                    "ci_low": (ci[0] if ci else None) if estimate.available else None,
                    "ci_high": (ci[1] if ci else None) if estimate.available else None,
                    "expectancy_r": estimate.expectancy_r if estimate.available else None,
                    "min_samples": min_samples,
                    "reason": estimate.reason,
                },
                "updated_at": r.updated_at.isoformat(),
            }
        )
    return {"min_samples": min_samples, "buckets": out}
