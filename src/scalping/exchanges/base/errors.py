"""Exchange-adapter error taxonomy, shared across REST/WS/algo paths."""

from __future__ import annotations


class ExchangeError(Exception):
    """Base for all exchange adapter errors."""


class RateLimited(ExchangeError):
    """Local token bucket exhausted, or exchange returned 429/418."""


class OrderRejected(ExchangeError):
    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"order rejected ({code}): {message}")


class LegacyConditionalOrderRejected(OrderRejected):
    """Binance error -4120: legacy STOP_*/TAKE_PROFIT_* on /fapi/v1/order.

    PLAN_OF_ACTION.md §2: since the algo-order migration, conditional orders must go
    through POST /fapi/v1/algoOrder. Raised so callers cannot silently fall back to
    the legacy path.
    """


class AmbiguousOrderResponse(ExchangeError):
    """Network/timeout ambiguity: order may or may not have been placed/canceled.

    Must be resolved via an order query before any retry (PLAN §K).
    """


class WebSocketCategoryMixError(ExchangeError):
    """Attempted to subscribe streams from more than one category
    (public/market/private) on a single connection — forbidden by PLAN_OF_ACTION.md §2.
    """


class StaleMarketData(ExchangeError):
    """A feed's data_age_ms exceeded the configured staleness threshold."""


class SelfCheckFailed(ExchangeError):
    """Startup self-check (PLAN §2a) detected a divergence from the expected exchange
    contract. Trading must refuse to start."""
