"""Core domain models shared across the pipeline.

Deliberately plain, immutable-by-default pydantic models — no ORM coupling here.
`persistence/models.py` maps these to SQLAlchemy rows; keeping the split means the
strategy/risk/execution code never touches SQLAlchemy.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class Side(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class Candle(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    timeframe: Literal["1m", "3m", "5m", "15m"]
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    quote_volume: float
    is_closed: bool = True


class BookTicker(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    bid_price: float
    bid_qty: float
    ask_price: float
    ask_qty: float
    event_time: datetime

    @property
    def mid(self) -> float:
        return (self.bid_price + self.ask_price) / 2

    @property
    def spread_bps(self) -> float:
        return (self.ask_price - self.bid_price) / self.mid * 10_000


class RejectionReason(StrEnum):
    """strategy-caems.md §Rejection reasons — persisted for research on every
    evaluation that does not produce a signal."""

    NO_5M_TREND = "NO_5M_TREND"
    DEAD_BAND_TOO_SMALL = "DEAD_BAND_TOO_SMALL"
    STRENGTH_TOO_EXTREME = "STRENGTH_TOO_EXTREME"
    PRICE_CONFIRMATION_FAILED = "PRICE_CONFIRMATION_FAILED"
    ENTRY_TOO_EXTENDED = "ENTRY_TOO_EXTENDED"
    LOW_VOLUME = "LOW_VOLUME"
    BAR_RANGE_ABNORMAL = "BAR_RANGE_ABNORMAL"
    FUNDING_BLACKOUT = "FUNDING_BLACKOUT"
    SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"
    BTC_REGIME_VETO = "BTC_REGIME_VETO"
    COST_TOO_HIGH = "COST_TOO_HIGH"
    EXPECTED_EDGE_TOO_LOW = "EXPECTED_EDGE_TOO_LOW"
    RISK_LIMIT = "RISK_LIMIT"
    DRAW_DOWN_LIMIT = "DRAW_DOWN_LIMIT"
    STALE_MARKET_DATA = "STALE_MARKET_DATA"
    INVALID_BOOK = "INVALID_BOOK"
    SYMBOL_DISABLED = "SYMBOL_DISABLED"
    LIQUIDITY_TOO_LOW = "LIQUIDITY_TOO_LOW"
    KILL_SWITCH = "KILL_SWITCH"
    SHORTS_DISABLED = "SHORTS_DISABLED"


class StrategyEvaluation(BaseModel):
    """Result of one CAEMS evaluation: logged whether it accepts or rejects.

    `strength` is always populated (strategy-caems.md: "Logged on every evaluation").
    """

    model_config = ConfigDict(frozen=True)

    symbol: str
    side: Side
    evaluated_at: datetime
    strength: float
    config_hash: str
    accepted: bool
    rejection_reason: RejectionReason | None = None

    def model_post_init(self, __context: object) -> None:
        if self.accepted and self.rejection_reason is not None:
            raise ValueError("accepted evaluation must not carry a rejection_reason")
        if not self.accepted and self.rejection_reason is None:
            raise ValueError("rejected evaluation must carry a rejection_reason")


class SignalCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    side: Side
    strategy_version: str
    signal_time: datetime
    entry_reference: float
    stop: float
    take_profit: float
    strength: float
    config_hash: str


class OrderType(StrEnum):
    LIMIT_MAKER = "LIMIT_MAKER"  # GTX
    MARKET = "MARKET"
    STOP_MARKET = "STOP_MARKET"
    TAKE_PROFIT_MARKET = "TAKE_PROFIT_MARKET"


class OrderStatus(StrEnum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class Order(BaseModel):
    model_config = ConfigDict(frozen=True)

    client_order_id: str
    exchange_order_id: str | None = None
    symbol: str
    side: Side
    order_type: OrderType
    price: float | None = None
    quantity: float
    reduce_only: bool = False
    close_position: bool = False
    status: OrderStatus = OrderStatus.NEW
    created_at: datetime


class Fill(BaseModel):
    model_config = ConfigDict(frozen=True)

    client_order_id: str
    symbol: str
    side: Side
    price: float
    quantity: float
    fee: float
    is_maker: bool
    fill_time: datetime


class EntryOutcome(StrEnum):
    """strategy-caems.md §Adverse-selection instrumentation."""

    MAKER_FILL = "MAKER_FILL"
    PARTIAL = "PARTIAL"
    TAKER_CONVERT = "TAKER_CONVERT"
    ABANDONED = "ABANDONED"


class Position(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    side: Side
    entry_price: float
    quantity: float
    stop_price: float
    take_profit_price: float
    opened_at: datetime
    protected: bool = False
    breakeven_moved: bool = False


class Trade(BaseModel):
    model_config = ConfigDict(frozen=True)

    trade_id: str
    symbol: str
    side: Side
    entry_price: float
    exit_price: float
    quantity: float
    r_multiple: float
    opened_at: datetime
    closed_at: datetime
    exit_reason: str
    config_hash: str
    mae: float | None = None
    mfe: float | None = None


class RiskDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    approved: bool
    reason: RejectionReason | None = None
    size: float | None = None
