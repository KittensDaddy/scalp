"""Control endpoints — PLAN_OF_ACTION.md §5/§6a: `Authorization: Bearer <token>`
required; kill-switch clear additionally requires the un-kill token. The route
layer only extracts the bearer token and translates `Unauthorized` to 401 — all
the actual asymmetry logic lives in `risk.kill_switch.KillSwitch`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from scalping.api.deps import AppState, get_session, get_state
from scalping.risk.kill_switch import Unauthorized

router = APIRouter(prefix="/api/v1/control", tags=["control"])


def _extract_bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    return authorization.removeprefix("Bearer ").strip()


@router.post("/kill-switch")
async def engage_kill_switch(
    reason: str = "manual",
    authorization: str | None = Header(default=None),
    state: AppState = Depends(get_state),
    session: AsyncSession = Depends(get_session),
):
    token = _extract_bearer(authorization)
    try:
        state.kill_switch.engage(token, reason)
    except Unauthorized as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    await state.kill_switch.persist(session)
    await session.commit()
    return {"killed": True}


@router.delete("/kill-switch")
async def clear_kill_switch(
    authorization: str | None = Header(default=None),
    state: AppState = Depends(get_state),
    session: AsyncSession = Depends(get_session),
):
    token = _extract_bearer(authorization)
    try:
        state.kill_switch.clear(token)
    except Unauthorized as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    await state.kill_switch.persist(session)
    await session.commit()
    return {"killed": False}


@router.get("/kill-switch")
async def kill_switch_status(state: AppState = Depends(get_state)):
    return {"killed": state.kill_switch.killed}
