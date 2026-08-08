"""SQLAlchemy models — PostgreSQL-compatible schema, SQLite for now.

Every signal/rejection/trade row carries `config_hash` (PLAN_OF_ACTION.md §3) so
results remain attributable after config edits. Columns use portable types (String,
Float, JSON, DateTime) — nothing SQLite-specific — so a later swap to Postgres is a
connection-string change, not a schema rewrite.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SignalRow(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    side: Mapped[str] = mapped_column(String)
    strategy_version: Mapped[str] = mapped_column(String, index=True)
    signal_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    entry_reference: Mapped[float] = mapped_column(Float)
    stop: Mapped[float] = mapped_column(Float)
    take_profit: Mapped[float] = mapped_column(Float)
    strength: Mapped[float] = mapped_column(Float)
    config_hash: Mapped[str] = mapped_column(String, index=True)
    preset_id: Mapped[str | None] = mapped_column(String, nullable=True)
    preset_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    features: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    score_breakdown: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    regime: Mapped[str | None] = mapped_column(String, nullable=True)
    session: Mapped[str | None] = mapped_column(String, nullable=True)


class RejectionRow(Base):
    __tablename__ = "rejections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    side: Mapped[str] = mapped_column(String)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    strength: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String, index=True)
    config_hash: Mapped[str] = mapped_column(String, index=True)


class TradeRow(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    strategy_version: Mapped[str] = mapped_column(String, index=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    side: Mapped[str] = mapped_column(String)
    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    r_multiple: Mapped[float] = mapped_column(Float)
    opened_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    closed_at: Mapped[datetime] = mapped_column(DateTime)
    exit_reason: Mapped[str] = mapped_column(String)
    config_hash: Mapped[str] = mapped_column(String, index=True)
    preset_id: Mapped[str | None] = mapped_column(String, nullable=True)
    preset_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mae: Mapped[float | None] = mapped_column(Float, nullable=True)
    mfe: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_at_exit: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_breakdown: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class EntryAttemptRow(Base):
    """Adverse-selection instrumentation — strategy-caems.md §Adverse-selection."""

    __tablename__ = "entry_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    side: Mapped[str] = mapped_column(String)
    outcome: Mapped[str] = mapped_column(String, index=True)
    attempted_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    fill_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    markout_5s_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    markout_30s_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    markout_5s_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    markout_30s_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    config_hash: Mapped[str] = mapped_column(String, index=True)


class SelfCheckRow(Base):
    """PLAN_OF_ACTION.md §2a startup self-check results, persisted with timestamps."""

    __tablename__ = "self_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    environment: Mapped[str] = mapped_column(String)
    passed: Mapped[bool] = mapped_column(Boolean)
    details: Mapped[dict] = mapped_column(JSON)


class KillSwitchRow(Base):
    """Persisted hard-kill state, honored at startup (PLAN_OF_ACTION.md §5)."""

    __tablename__ = "kill_switch"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    killed: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    set_at: Mapped[datetime] = mapped_column(DateTime)


class ProtectionEventRow(Base):
    """t_protection_ms per trade (PLAN_OF_ACTION.md §5a) — backs /health's
    protection-gap p50/p99 (PLAN §6a)."""

    __tablename__ = "protection_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    measured_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    t_protection_ms: Mapped[float] = mapped_column(Float)
    protected: Mapped[bool] = mapped_column(Boolean)


class SymbolUniverseRow(Base):
    """SCANNER_DASHBOARD_PLAN.md §H: symbol_universe (symbol, status,
    filters_passed JSON, updated_at). One row per symbol, upserted on each
    universe refresh so the dashboard can show *why* a symbol is untradable."""

    __tablename__ = "symbol_universe"

    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    eligible: Mapped[bool] = mapped_column(Boolean)
    filters_passed: Mapped[dict] = mapped_column(JSON)
    reasons: Mapped[list] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class CooldownRow(Base):
    """SCANNER_DASHBOARD_PLAN.md §H: cooldowns (scope, symbol, strategy, reason,
    until_ts)."""

    __tablename__ = "cooldowns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String, index=True)
    key: Mapped[str] = mapped_column(String, index=True)
    reason: Mapped[str] = mapped_column(String)
    until_ts: Mapped[datetime] = mapped_column(DateTime, index=True)


class DevelopingSetupRow(Base):
    """SCANNER_DASHBOARD_PLAN.md §H: developing_setups (symbol, strategy, ts, score,
    missing_conditions JSON, projection JSON)."""

    __tablename__ = "developing_setups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    side: Mapped[str] = mapped_column(String)
    strategy_version: Mapped[str] = mapped_column(String, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    score: Mapped[float] = mapped_column(Float)
    missing_conditions: Mapped[list] = mapped_column(JSON)
    projections: Mapped[dict] = mapped_column(JSON)
