"""Campaign-level reads over persisted paper/testnet forward data.

Everything the go-live evidence bar (PLAN_OF_ACTION.md §8) and the drawdown
machine need to survive a process restart lives in `trades` / `entry_attempts`
already — these queries assemble it rather than introducing a parallel counter
that could drift from the trade record.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from scalping.domain.models import EntryOutcome
from scalping.persistence.models import EntryAttemptRow, TradeRow


def _naive(ts: datetime) -> datetime:
    return ts.replace(tzinfo=None) if ts.tzinfo is not None else ts


def day_start(now: datetime) -> datetime:
    """00:00 UTC of `now`'s day — the daily loss cap's reset boundary."""
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def week_start(now: datetime) -> datetime:
    """00:00 UTC of `now`'s ISO week (Monday) — the weekly cap's boundary."""
    return day_start(now) - timedelta(days=now.weekday())


@dataclass(frozen=True)
class DrawdownSnapshot:
    daily_r: float
    weekly_r: float
    trade_r_history: list[float]


async def load_drawdown_snapshot(
    session: AsyncSession, *, now: datetime | None = None
) -> DrawdownSnapshot:
    """Rebuild daily/weekly realized R from the trade record.

    Restoring this at startup is what stops a crash-and-restart from silently
    handing the strategy a fresh loss budget mid-campaign.
    """
    now = now or datetime.now(UTC)
    week = _naive(week_start(now))
    day = _naive(day_start(now))

    stmt = (
        select(TradeRow.r_multiple, TradeRow.closed_at)
        .where(TradeRow.closed_at >= week)
        .order_by(TradeRow.closed_at)
    )
    rows = (await session.execute(stmt)).all()

    daily = sum(r for r, closed_at in rows if closed_at >= day)
    weekly = sum(r for r, _ in rows)
    return DrawdownSnapshot(
        daily_r=float(daily),
        weekly_r=float(weekly),
        trade_r_history=[float(r) for r, _ in rows],
    )


async def load_trade_r_multiples(session: AsyncSession) -> list[float]:
    """Every completed trade's R, oldest first — the evidence bar's sample."""
    stmt = select(TradeRow.r_multiple).order_by(TradeRow.closed_at, TradeRow.id)
    return [float(r) for r in (await session.execute(stmt)).scalars().all()]


async def count_entry_attempts(session: AsyncSession) -> int:
    return int(
        (await session.execute(select(func.count()).select_from(EntryAttemptRow))).scalar_one()
    )


@dataclass(frozen=True)
class MarkoutSample:
    maker_30s_bps: list[float]
    taker_30s_bps: list[float]

    @property
    def n(self) -> int:
        return len(self.maker_30s_bps) + len(self.taker_30s_bps)


async def load_markouts_by_entry_type(session: AsyncSession) -> MarkoutSample:
    """Split recorded 30s markouts into the maker and taker arms of the
    pre-registered decision rule. Attempts without a markout yet are excluded —
    a missing measurement is not a zero."""
    stmt = select(EntryAttemptRow.outcome, EntryAttemptRow.markout_30s_bps).where(
        EntryAttemptRow.markout_30s_bps.is_not(None)
    )
    maker: list[float] = []
    taker: list[float] = []
    for outcome, markout in (await session.execute(stmt)).all():
        if outcome == EntryOutcome.MAKER_FILL.value:
            maker.append(float(markout))
        elif outcome == EntryOutcome.TAKER_CONVERT.value:
            taker.append(float(markout))
    return MarkoutSample(maker_30s_bps=maker, taker_30s_bps=taker)
