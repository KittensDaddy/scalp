"""Journal enrichment — SCANNER_DASHBOARD_PLAN.md §S9.

Pure helpers that turn a closed trade + context into MAE/MFE, score-at-exit,
cost breakdown, and auto-notes. No I/O; the persistence layer just stores the
returned fields on `TradeRow`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class CostBreakdown:
    fees_r: float
    spread_r: float
    slippage_r: float
    funding_r: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {
            "fees_r": self.fees_r,
            "spread_r": self.spread_r,
            "slippage_r": self.slippage_r,
            "funding_r": self.funding_r,
        }

    @property
    def total_r(self) -> float:
        return self.fees_r + self.spread_r + self.slippage_r + self.funding_r


@dataclass(frozen=True)
class EnrichedTradeJournal:
    trade_id: str
    symbol: str
    side: str
    r_multiple: float
    mae_r: float
    mfe_r: float
    score_at_exit: float | None
    cost_breakdown: CostBreakdown
    auto_notes: list[str]
    regime: str | None
    session: str | None
    strategy_version: str
    opened_at: datetime
    closed_at: datetime
    exit_reason: str
    hour_utc: int


def build_auto_notes(
    *,
    r_multiple: float,
    mae_r: float,
    mfe_r: float,
    exit_reason: str,
    protected: bool,
    breakeven_moved: bool,
    score_at_entry: float | None,
    score_at_exit: float | None,
) -> list[str]:
    notes: list[str] = []
    if not protected:
        notes.append("closed without confirmed protection")
    if breakeven_moved:
        notes.append("breakeven stop was moved")
    if mae_r >= 0.9 and r_multiple > 0:
        notes.append("deep adverse excursion recovered to a win")
    if mfe_r >= 1.0 and r_multiple < 0.5 and exit_reason != "TAKE_PROFIT":
        notes.append("gave back ≥1R of favorable excursion")
    if score_at_entry is not None and score_at_exit is not None:
        delta = score_at_exit - score_at_entry
        if delta <= -10:
            notes.append(f"score decayed {delta:.0f} pts by exit")
        elif delta >= 10:
            notes.append(f"score improved {delta:.0f} pts by exit")
    if exit_reason == "TIME_STOP":
        notes.append("time stop exited the trade")
    return notes


def enrich_trade(
    *,
    trade_id: str,
    symbol: str,
    side: str,
    r_multiple: float,
    mae_r: float,
    mfe_r: float,
    exit_reason: str,
    opened_at: datetime,
    closed_at: datetime,
    strategy_version: str,
    cost: CostBreakdown,
    score_at_exit: float | None = None,
    score_at_entry: float | None = None,
    regime: str | None = None,
    session: str | None = None,
    protected: bool = True,
    breakeven_moved: bool = False,
) -> EnrichedTradeJournal:
    notes = build_auto_notes(
        r_multiple=r_multiple,
        mae_r=mae_r,
        mfe_r=mfe_r,
        exit_reason=exit_reason,
        protected=protected,
        breakeven_moved=breakeven_moved,
        score_at_entry=score_at_entry,
        score_at_exit=score_at_exit,
    )
    return EnrichedTradeJournal(
        trade_id=trade_id,
        symbol=symbol,
        side=side,
        r_multiple=r_multiple,
        mae_r=mae_r,
        mfe_r=mfe_r,
        score_at_exit=score_at_exit,
        cost_breakdown=cost,
        auto_notes=notes,
        regime=regime,
        session=session,
        strategy_version=strategy_version,
        opened_at=opened_at,
        closed_at=closed_at,
        exit_reason=exit_reason,
        hour_utc=closed_at.hour,
    )


@dataclass(frozen=True)
class AnalyticsGroup:
    key: str
    n: int
    wins: int
    sum_r: float
    avg_r: float | None
    win_rate: float | None
    avg_mae: float | None
    avg_mfe: float | None
    profit_factor: float | None


def _group_key(trade: dict[str, Any], group_by: str) -> str:
    if group_by == "hour":
        closed = trade.get("closed_at")
        if isinstance(closed, datetime):
            return f"{closed.hour:02d}"
        return str(trade.get("hour_utc", "?"))
    value = trade.get(group_by)
    return "unknown" if value is None else str(value)


def group_analytics(
    trades: list[dict[str, Any]], *, group_by: str
) -> list[AnalyticsGroup]:
    """Group enriched trade dicts by strategy/symbol/side/regime/session/hour/exit_reason."""
    allowed = {
        "strategy", "strategy_version", "symbol", "side", "regime", "session",
        "hour", "exit_reason", "bucket",
    }
    if group_by not in allowed:
        raise ValueError(f"unsupported group_by {group_by!r}; allowed={sorted(allowed)}")

    buckets: dict[str, dict[str, float]] = {}
    for t in trades:
        key = _group_key(t, "strategy_version" if group_by == "strategy" else group_by)
        b = buckets.setdefault(
            key, {"n": 0, "wins": 0, "sum_r": 0.0, "sum_mae": 0.0, "sum_mfe": 0.0,
                  "gross_win": 0.0, "gross_loss": 0.0}
        )
        r = float(t.get("r_multiple", 0.0))
        b["n"] += 1
        b["sum_r"] += r
        b["sum_mae"] += float(t.get("mae_r") or t.get("mae") or 0.0)
        b["sum_mfe"] += float(t.get("mfe_r") or t.get("mfe") or 0.0)
        if r > 0:
            b["wins"] += 1
            b["gross_win"] += r
        else:
            b["gross_loss"] += -r

    groups: list[AnalyticsGroup] = []
    for key, b in buckets.items():
        n = int(b["n"])
        pf: float | None
        if b["gross_loss"] == 0:
            pf = float("inf") if b["gross_win"] > 0 else None
        else:
            pf = b["gross_win"] / b["gross_loss"]
        groups.append(
            AnalyticsGroup(
                key=key,
                n=n,
                wins=int(b["wins"]),
                sum_r=b["sum_r"],
                avg_r=b["sum_r"] / n if n else None,
                win_rate=b["wins"] / n if n else None,
                avg_mae=b["sum_mae"] / n if n else None,
                avg_mfe=b["sum_mfe"] / n if n else None,
                profit_factor=pf,
            )
        )
    return sorted(groups, key=lambda g: g.sum_r, reverse=True)
