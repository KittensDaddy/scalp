"""`/evidence` — the PLAN §8 go-live bar, machine-checked against live campaign data.

Read-only and deliberately unforgiving: the testnet ops criteria (§8.7, §8.8)
report unverified unless the operator asserts them explicitly per request, so a
paper campaign can never render an overall PASS on its own.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from scalping.api.deps import AppState, get_session, get_state
from scalping.edge.campaign import OpsAttestation, build_campaign_evidence

router = APIRouter(prefix="/api/v1", tags=["evidence"])


@router.get("/evidence")
async def evidence(
    session: AsyncSession = Depends(get_session),
    state: AppState = Depends(get_state),
    clean_restarts: int = Query(
        0, ge=0, description="§8.7 — forced restarts reconciled clean (operator-asserted)"
    ),
    clean_disconnects: int = Query(
        0, ge=0, description="§8.7 — forced disconnects reconciled clean (operator-asserted)"
    ),
    kill_switch_verified: bool = Query(
        False, description="§8.8 — kill switch verified end-to-end on testnet (operator-asserted)"
    ),
    n_bootstrap: int = Query(2000, ge=200, le=20000),
):
    campaign = await build_campaign_evidence(
        session,
        config=state.settings.defaults,
        ops=OpsAttestation(
            clean_restarts=clean_restarts,
            clean_disconnects=clean_disconnects,
            kill_switch_verified=kill_switch_verified,
        ),
        n_bootstrap=n_bootstrap,
    )
    report = campaign.report
    return {
        "passed": report.passed,
        "criteria": [
            {"name": c.name, "passed": c.passed, "detail": c.detail} for c in report.criteria
        ],
        "summary": report.summary(),
        "sample": {
            "n_trades": campaign.n_trades,
            "n_entry_attempts": campaign.n_entry_attempts,
            "n_markouts": campaign.n_markouts,
            "protection_gap_p99_ms": campaign.protection_gap_p99_ms,
        },
        "maker_taker": {
            "resolved": campaign.maker_taker.resolved,
            "switch_to_taker": campaign.maker_taker.switch_to_taker,
            "avg_maker_30s_bps": campaign.maker_taker.avg_maker_30s_bps,
            "avg_taker_30s_bps": campaign.maker_taker.avg_taker_30s_bps,
            "detail": campaign.maker_taker.detail,
        },
    }
