"""Closed-trade + calibration persistence for the paper/live campaign."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scalping.accounting.journal import CostBreakdown, enrich_trade
from scalping.edge.calibration import (
    CalibrationKey,
    CalibrationStats,
    accumulate_calibration,
    score_bucket,
    wilson_ci,
)
from scalping.monitoring.active_trades import ActiveTrade
from scalping.persistence.models import CalibrationStatsRow, EntryAttemptRow, TradeRow


def _naive(ts: datetime) -> datetime:
    return ts.replace(tzinfo=None) if ts.tzinfo is not None else ts


async def save_closed_trade(
    session: AsyncSession,
    *,
    trade: ActiveTrade,
    config_hash: str,
    cost: CostBreakdown | None = None,
    regime: str | None = None,
    session_name: str | None = None,
    preset_id: str | None = None,
    preset_version: int | None = None,
) -> TradeRow:
    """Persist an enriched closed trade. Idempotent on `trade_id`."""
    if not trade.closed or trade.closed_at is None or trade.exit_reason is None:
        raise ValueError(f"trade {trade.trade_id} is not closed")

    existing = (
        await session.execute(select(TradeRow).where(TradeRow.trade_id == trade.trade_id))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    cost = cost or CostBreakdown(fees_r=0.0, spread_r=0.0, slippage_r=0.0)
    journal = enrich_trade(
        trade_id=trade.trade_id,
        symbol=trade.symbol,
        side=trade.side.value,
        r_multiple=trade.unrealized_r,
        mae_r=trade.mae_r,
        mfe_r=trade.mfe_r,
        exit_reason=trade.exit_reason,
        opened_at=trade.opened_at,
        closed_at=trade.closed_at,
        strategy_version=trade.strategy_version,
        cost=cost,
        score_at_exit=trade.score,
        score_at_entry=trade.score,
        regime=regime,
        session=session_name,
        protected=trade.protected,
        breakeven_moved=trade.breakeven_moved,
    )
    breakdown = cost.as_dict()
    breakdown["auto_notes"] = journal.auto_notes
    if regime is not None:
        breakdown["regime"] = regime
    if session_name is not None:
        breakdown["session"] = session_name

    row = TradeRow(
        trade_id=trade.trade_id,
        strategy_version=trade.strategy_version,
        symbol=trade.symbol,
        side=trade.side.value,
        entry_price=trade.entry_price,
        exit_price=trade.current_price,
        quantity=trade.quantity,
        r_multiple=trade.unrealized_r,
        opened_at=_naive(trade.opened_at),
        closed_at=_naive(trade.closed_at),
        exit_reason=trade.exit_reason,
        config_hash=config_hash,
        preset_id=preset_id,
        preset_version=preset_version,
        mae=trade.mae_r,
        mfe=trade.mfe_r,
        score_at_exit=trade.score,
        cost_breakdown=breakdown,
    )
    session.add(row)
    return row


async def save_entry_attempt(
    session: AsyncSession,
    *,
    symbol: str,
    side: str,
    outcome: str,
    attempted_at: datetime,
    config_hash: str,
    fill_price: float | None = None,
    fill_time: datetime | None = None,
) -> EntryAttemptRow:
    row = EntryAttemptRow(
        symbol=symbol,
        side=side,
        outcome=outcome,
        attempted_at=_naive(attempted_at),
        fill_price=fill_price,
        fill_time=_naive(fill_time) if fill_time is not None else None,
        markout_5s_bps=None,
        markout_30s_bps=None,
        markout_5s_r=None,
        markout_30s_r=None,
        config_hash=config_hash,
    )
    session.add(row)
    # Flush so the caller gets the surrogate key: markouts are measured seconds
    # after the fill and land as an update to this row.
    await session.flush()
    return row


async def update_entry_attempt_markouts(
    session: AsyncSession,
    *,
    attempt_id: int,
    markout_5s_bps: float | None = None,
    markout_5s_r: float | None = None,
    markout_30s_bps: float | None = None,
    markout_30s_r: float | None = None,
) -> EntryAttemptRow | None:
    """Fill in markouts once the +5s / +30s mids have been observed.

    Each offset is written independently — a process that dies between the two
    samples leaves an honest partial row rather than discarding the 5s reading.
    """
    row = (
        await session.execute(select(EntryAttemptRow).where(EntryAttemptRow.id == attempt_id))
    ).scalar_one_or_none()
    if row is None:
        return None
    if markout_5s_bps is not None:
        row.markout_5s_bps = markout_5s_bps
    if markout_5s_r is not None:
        row.markout_5s_r = markout_5s_r
    if markout_30s_bps is not None:
        row.markout_30s_bps = markout_30s_bps
    if markout_30s_r is not None:
        row.markout_30s_r = markout_30s_r
    return row


async def record_calibration_sample(
    session: AsyncSession,
    *,
    strategy_version: str,
    side: str,
    regime: str,
    score: float | None,
    r_multiple: float,
    updated_at: datetime,
) -> CalibrationStatsRow:
    """Accumulate one closed-trade sample into calibration_stats."""
    bucket = score_bucket(score) if score is not None else "unknown"
    key = CalibrationKey(
        strategy_version=strategy_version,
        side=side,
        regime=regime,
        score_bucket=bucket,
    )
    existing_row = (
        await session.execute(
            select(CalibrationStatsRow).where(
                CalibrationStatsRow.strategy_version == key.strategy_version,
                CalibrationStatsRow.side == key.side,
                CalibrationStatsRow.regime == key.regime,
                CalibrationStatsRow.score_bucket == key.score_bucket,
            )
        )
    ).scalar_one_or_none()

    existing_stats = None
    if existing_row is not None:
        existing_stats = CalibrationStats(
            key=key,
            n=existing_row.n,
            wins=existing_row.wins,
            sum_r=existing_row.sum_r,
            updated_at=existing_row.updated_at,
        )
    updated = accumulate_calibration(
        existing_stats,
        key=key,
        r_multiple=r_multiple,
        won=r_multiple > 0,
        updated_at=updated_at,
    )
    ci = wilson_ci(updated.wins, updated.n)
    if existing_row is None:
        row = CalibrationStatsRow(
            strategy_version=key.strategy_version,
            side=key.side,
            regime=key.regime,
            score_bucket=key.score_bucket,
            n=updated.n,
            wins=updated.wins,
            sum_r=updated.sum_r,
            ci_low=ci[0] if ci else None,
            ci_high=ci[1] if ci else None,
            updated_at=_naive(updated_at),
        )
        session.add(row)
        return row

    existing_row.n = updated.n
    existing_row.wins = updated.wins
    existing_row.sum_r = updated.sum_r
    existing_row.ci_low = ci[0] if ci else None
    existing_row.ci_high = ci[1] if ci else None
    existing_row.updated_at = _naive(updated_at)
    return existing_row
