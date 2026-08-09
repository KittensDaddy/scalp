"""Strategy Lab presets + backtests API — DASHBOARD_STRATEGY_LAB.md L1-L6."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scalping.api.deps import AppState, get_session, get_state
from scalping.config.presets import ClassPreset
from scalping.lab.backtest_jobs import (
    SANITY_BANNER,
    BacktestJobStatus,
    compare_jobs,
)
from scalping.lab.presets import (
    can_activate_live,
    resolve_with_provenance,
    validate_new_version_params,
)
from scalping.persistence.models import BacktestJobRow, PresetRow, TradeRow

router = APIRouter(prefix="/api/v1", tags=["lab"])


def _require_control(state: AppState, authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if token != state.settings.control_token:
        raise HTTPException(status_code=401, detail="invalid control token")
    return token


class PresetVersionBody(BaseModel):
    params: dict[str, Any]
    author: str = "dashboard"
    note: str = ""
    class_rule: dict[str, Any] = Field(default_factory=dict)
    overlay: bool = False


class ActivateBody(BaseModel):
    version: int
    confirm: bool = False


class BacktestBody(BaseModel):
    preset_id: str
    preset_version: int
    symbols: list[str]
    date_from: datetime
    date_to: datetime
    mode: str = "CANDLE"


class CompareBody(BaseModel):
    job_ids: list[str]


@router.get("/presets")
async def list_presets(session: AsyncSession = Depends(get_session)):
    stmt = select(PresetRow).order_by(PresetRow.created_at.desc())
    rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "preset_id": r.preset_id,
            "name": r.name,
            "version": r.version,
            "overlay": r.overlay,
            "disabled": r.disabled,
            "params": r.params,
            "class_rule": r.class_rule,
            "activated_paper": r.activated_paper,
            "activated_live": r.activated_live,
            "author": r.author,
            "note": r.note,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/presets/{preset_id}/effective")
async def preset_effective(
    preset_id: str,
    symbol: str = "BTCUSDT",
    state: AppState = Depends(get_state),
    session: AsyncSession = Depends(get_session),
):
    stmt = (
        select(PresetRow)
        .where(PresetRow.preset_id == preset_id)
        .order_by(PresetRow.version.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="preset not found")
    class_preset = ClassPreset(
        name=row.name, version=row.version, overlay=row.overlay,
        disabled=row.disabled, values=row.params,
    )
    overlays = [class_preset] if row.overlay else []
    base = None if row.overlay else class_preset
    view = resolve_with_provenance(state.settings.defaults, base, overlays)
    return {
        "preset_id": preset_id,
        "symbol": symbol,
        "version": row.version,
        "config_hash": view.config.config_hash(),
        "provenance": [
            {"key": p.key, "value": p.value, "layer": p.layer} for p in view.provenance
        ],
    }


@router.post("/presets/{preset_id}/versions")
async def create_preset_version(
    preset_id: str,
    body: PresetVersionBody,
    state: AppState = Depends(get_state),
    session: AsyncSession = Depends(get_session),
    authorization: str | None = Header(default=None),
):
    _require_control(state, authorization)
    try:
        validate_new_version_params(
            body.params, overlay=body.overlay, name=preset_id,
        )
    except Exception as exc:  # FrozenStrategyError | KeyError | PresetOverlayViolation
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    latest = (
        await session.execute(
            select(PresetRow)
            .where(PresetRow.preset_id == preset_id)
            .order_by(PresetRow.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    next_version = 1 if latest is None else latest.version + 1
    name = latest.name if latest is not None else preset_id
    row = PresetRow(
        preset_id=preset_id,
        name=name,
        version=next_version,
        class_rule=body.class_rule or (latest.class_rule if latest else {}),
        params=body.params,
        overlay=body.overlay,
        disabled=False,
        created_at=datetime.now(UTC).replace(tzinfo=None),
        author=body.author,
        note=body.note,
        activated_paper=False,
        activated_live=False,
    )
    session.add(row)
    await session.commit()
    return {"preset_id": preset_id, "version": next_version}


@router.post("/presets/{preset_id}/activate")
async def activate_paper(
    preset_id: str,
    body: ActivateBody,
    state: AppState = Depends(get_state),
    session: AsyncSession = Depends(get_session),
    authorization: str | None = Header(default=None),
):
    _require_control(state, authorization)
    row = (
        await session.execute(
            select(PresetRow).where(
                PresetRow.preset_id == preset_id, PresetRow.version == body.version
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="preset version not found")
    # clear other paper pins for this preset_id
    others = (
        await session.execute(select(PresetRow).where(PresetRow.preset_id == preset_id))
    ).scalars().all()
    for o in others:
        o.activated_paper = o.version == body.version
    await session.commit()
    return {"preset_id": preset_id, "version": body.version, "activated": "paper"}


@router.post("/presets/{preset_id}/activate-live")
async def activate_live(
    preset_id: str,
    body: ActivateBody,
    state: AppState = Depends(get_state),
    session: AsyncSession = Depends(get_session),
    authorization: str | None = Header(default=None),
):
    _require_control(state, authorization)
    if not body.confirm:
        raise HTTPException(status_code=400, detail="confirm=true required for LIVE activation")
    row = (
        await session.execute(
            select(PresetRow).where(
                PresetRow.preset_id == preset_id, PresetRow.version == body.version
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="preset version not found")

    bt = (
        await session.execute(
            select(BacktestJobRow).where(
                BacktestJobRow.preset_id == preset_id,
                BacktestJobRow.preset_version == body.version,
                BacktestJobRow.status == BacktestJobStatus.COMPLETED.value,
            ).limit(1)
        )
    ).scalar_one_or_none()
    paper_n = (
        await session.execute(
            select(TradeRow).where(
                TradeRow.strategy_version
                == state.settings.defaults.frozen.strategy_version
            )
        )
    ).scalars().all()
    ok, reason = can_activate_live(
        has_completed_backtest=bt is not None,
        paper_trade_count=len(paper_n),
    )
    if not ok:
        raise HTTPException(status_code=409, detail=reason)
    others = (
        await session.execute(select(PresetRow).where(PresetRow.preset_id == preset_id))
    ).scalars().all()
    for o in others:
        o.activated_live = o.version == body.version
    await session.commit()
    return {"preset_id": preset_id, "version": body.version, "activated": "live"}


@router.post("/backtests")
async def enqueue_backtest(
    body: BacktestBody,
    state: AppState = Depends(get_state),
    session: AsyncSession = Depends(get_session),
    authorization: str | None = Header(default=None),
):
    """Enqueue a sanity-only candle backtest for a preset version."""
    _require_control(state, authorization)
    if body.mode != "CANDLE":
        raise HTTPException(status_code=400, detail="only mode=CANDLE is supported")
    if not body.symbols:
        raise HTTPException(status_code=400, detail="symbols required")
    if state.candle_loader is None:
        raise HTTPException(status_code=503, detail="candle_loader not configured")

    row = (
        await session.execute(
            select(PresetRow).where(
                PresetRow.preset_id == body.preset_id,
                PresetRow.version == body.preset_version,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="preset version not found")

    config = state.settings.defaults.model_copy(deep=True)
    # Apply preset gate params into EffectiveConfig.gates where keys match.
    gate_data = config.gates.model_dump()
    for k, v in (row.params or {}).items():
        if k in gate_data:
            gate_data[k] = v
    config = config.model_copy(update={"gates": config.gates.model_validate(gate_data)})

    try:
        candles_1m, candles_5m = await state.candle_loader(
            body.symbols, body.date_from, body.date_to
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"candle load failed: {exc}") from exc

    try:
        job = state.backtest_runner.enqueue(
            preset_id=body.preset_id,
            preset_version=body.preset_version,
            symbols=body.symbols,
            date_from=body.date_from,
            date_to=body.date_to,
            config=config,
            candles_1m=candles_1m,
            candles_5m=candles_5m,
            mode=body.mode,
            created_at=datetime.now(UTC),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    session.add(
        BacktestJobRow(
            job_id=job.job_id,
            preset_id=job.preset_id,
            preset_version=job.preset_version,
            symbols=job.symbols,
            date_from=body.date_from.replace(tzinfo=None),
            date_to=body.date_to.replace(tzinfo=None),
            mode=job.mode,
            status=job.status.value,
            progress=job.progress,
            result=None,
            created_at=job.created_at.replace(tzinfo=None),
            config_hash=job.config_hash,
            data_checksum=job.data_checksum,
            error=None,
        )
    )
    await session.commit()
    return {
        "job_id": job.job_id,
        "status": job.status.value,
        "banner": SANITY_BANNER,
        "preset_id": job.preset_id,
        "preset_version": job.preset_version,
    }


@router.get("/backtests/{job_id}")
async def get_backtest(job_id: str, state: AppState = Depends(get_state)):
    job = state.backtest_runner.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return {
        "job_id": job.job_id,
        "status": job.status.value,
        "progress": job.progress,
        "banner": SANITY_BANNER,
        "result": job.result,
        "error": job.error,
        "preset_id": job.preset_id,
        "preset_version": job.preset_version,
        "config_hash": job.config_hash,
        "data_checksum": job.data_checksum,
    }


@router.post("/backtests/compare")
async def compare_backtests(body: CompareBody, state: AppState = Depends(get_state)):
    jobs = []
    for jid in body.job_ids:
        job = state.backtest_runner.get(jid)
        if job is None:
            raise HTTPException(status_code=404, detail=f"job {jid} not found")
        jobs.append(job)
    try:
        rows = compare_jobs(jobs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "banner": SANITY_BANNER,
        "rows": [{"metric": r.metric, "values": r.values} for r in rows],
    }
