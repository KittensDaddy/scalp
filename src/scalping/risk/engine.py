"""Risk engine — sizing + drawdown + position caps, owns condition 11 (risk gate)
of strategy-caems.md and feeds `RiskCostDecision.risk_approved`/`risk_rejection`
into the CAEMS engine (P3).
"""

from __future__ import annotations

from dataclasses import dataclass

from scalping.config.settings import RiskConfig
from scalping.domain.models import RejectionReason, Side
from scalping.risk.drawdown import DrawdownState
from scalping.risk.exposure import ExposureLimiter
from scalping.risk.sizing import InvalidStopError, SizingInputs, compute_position_size


@dataclass(frozen=True)
class RiskRequest:
    symbol: str
    symbol_class: str
    side: Side
    entry: float
    stop: float
    equity: float
    available_depth: float
    bar_volume: float
    exchange_max_notional: float
    correlation_group: str | None = None


@dataclass(frozen=True)
class RiskApproval:
    approved: bool
    reason: RejectionReason | None = None
    size: float | None = None


class RiskEngine:
    """Tracks open-position counts and drawdown; the trading loop must call
    `on_position_opened`/`on_position_closed` to keep counts accurate, and
    `on_trade_closed` to feed the drawdown machine."""

    def __init__(
        self, drawdown: DrawdownState | None = None, exposure: ExposureLimiter | None = None
    ) -> None:
        self.drawdown = drawdown or DrawdownState()
        self.exposure = exposure or ExposureLimiter()
        self._open_total = 0
        self._open_by_class: dict[str, int] = {}

    def on_position_opened(self, symbol_class: str, correlation_group: str | None = None) -> None:
        self._open_total += 1
        self._open_by_class[symbol_class] = self._open_by_class.get(symbol_class, 0) + 1
        if correlation_group is not None:
            self.exposure.on_opened(correlation_group)

    def on_position_closed(self, symbol_class: str, correlation_group: str | None = None) -> None:
        self._open_total = max(0, self._open_total - 1)
        self._open_by_class[symbol_class] = max(0, self._open_by_class.get(symbol_class, 0) - 1)
        if correlation_group is not None:
            self.exposure.on_closed(correlation_group)

    def on_trade_closed(self, r_multiple: float) -> None:
        self.drawdown.record_trade(r_multiple)

    def evaluate(self, request: RiskRequest, risk_cfg: RiskConfig) -> RiskApproval:
        if self.drawdown.daily_limit_breached(risk_cfg.daily_loss_cap_r):
            return RiskApproval(approved=False, reason=RejectionReason.DRAW_DOWN_LIMIT)
        if self.drawdown.weekly_limit_breached(risk_cfg.weekly_loss_cap_r):
            return RiskApproval(approved=False, reason=RejectionReason.DRAW_DOWN_LIMIT)

        if self._open_total >= risk_cfg.max_positions_total:
            return RiskApproval(approved=False, reason=RejectionReason.RISK_LIMIT)
        if (
            self._open_by_class.get(request.symbol_class, 0)
            >= risk_cfg.max_positions_in_class
        ):
            return RiskApproval(approved=False, reason=RejectionReason.RISK_LIMIT)

        if request.correlation_group is not None and not self.exposure.within_limit(
            request.correlation_group, risk_cfg.max_positions_per_correlation_group
        ):
            return RiskApproval(approved=False, reason=RejectionReason.RISK_LIMIT)

        try:
            result = compute_position_size(
                SizingInputs(
                    equity=request.equity,
                    entry=request.entry,
                    stop=request.stop,
                    available_depth=request.available_depth,
                    bar_volume=request.bar_volume,
                    exchange_max_notional=request.exchange_max_notional,
                ),
                risk_cfg,
            )
        except InvalidStopError:
            return RiskApproval(approved=False, reason=RejectionReason.RISK_LIMIT)

        if result.size <= 0:
            return RiskApproval(approved=False, reason=RejectionReason.RISK_LIMIT)

        return RiskApproval(approved=True, size=result.size)
