"""Algo Order API — the only supported path for conditional orders.

PLAN_OF_ACTION.md §2: `POST /fapi/v1/algoOrder` since 2025-12-09; legacy
`STOP_*`/`TAKE_PROFIT_*` on `/fapi/v1/order` now rejects with -4120
(`LegacyConditionalOrderRejected`, see `exchanges/base/errors.py`). Stop types:
`STOP_MARKET`, `TAKE_PROFIT_MARKET`, `STOP`, `TAKE_PROFIT`, `TRAILING_STOP_MARKET`.
`reduceOnly`/`closePosition` supported.

Full self-check + protection-gap wiring lands in P6/P7; this module is the thin,
directly-testable client surface they build on.
"""

from __future__ import annotations

from typing import Any

from scalping.exchanges.base.rate_limiter import Budget
from scalping.exchanges.binance.rest import BinanceRestClient


class AlgoOrderClient:
    def __init__(self, rest: BinanceRestClient) -> None:
        self._rest = rest

    async def place_stop_market(
        self, symbol: str, side: str, stop_price: float, *,
        quantity: float | None = None, close_position: bool = False,
        reduce_only: bool = False, client_algo_id: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "algoType": "STOP_MARKET",
            "stopPrice": stop_price,
            "closePosition": close_position,
            "reduceOnly": reduce_only,
        }
        if quantity is not None:
            params["quantity"] = quantity
        if client_algo_id is not None:
            params["clientAlgoId"] = client_algo_id
        return await self._rest.request(
            "POST", "/fapi/v1/algoOrder", budget=Budget.ALGO_ORDER, params=params, signed=True
        )

    async def place_take_profit_market(
        self, symbol: str, side: str, stop_price: float, *,
        quantity: float | None = None, close_position: bool = False,
        reduce_only: bool = False, client_algo_id: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "algoType": "TAKE_PROFIT_MARKET",
            "stopPrice": stop_price,
            "closePosition": close_position,
            "reduceOnly": reduce_only,
        }
        if quantity is not None:
            params["quantity"] = quantity
        if client_algo_id is not None:
            params["clientAlgoId"] = client_algo_id
        return await self._rest.request(
            "POST", "/fapi/v1/algoOrder", budget=Budget.ALGO_ORDER, params=params, signed=True
        )

    async def cancel_algo_order(self, symbol: str, *, algo_id: int | None = None,
                                 client_algo_id: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"symbol": symbol}
        if algo_id is not None:
            params["algoId"] = algo_id
        if client_algo_id is not None:
            params["clientAlgoId"] = client_algo_id
        return await self._rest.request(
            "DELETE", "/fapi/v1/algoOrder", budget=Budget.ALGO_ORDER, params=params, signed=True
        )

    async def query_algo_order(self, symbol: str, *, algo_id: int | None = None,
                                client_algo_id: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"symbol": symbol}
        if algo_id is not None:
            params["algoId"] = algo_id
        if client_algo_id is not None:
            params["clientAlgoId"] = client_algo_id
        return await self._rest.request(
            "GET", "/fapi/v1/algoOrder", budget=Budget.ALGO_ORDER, params=params, signed=True
        )

    async def submit_and_cancel_minimal_stop(
        self, symbol: str, *, far_stop_price: float, quantity: float,
    ) -> dict[str, Any]:
        """PLAN_OF_ACTION.md §2a startup self-check step: place a minimal algo
        order far enough from market to never trigger, then cancel it, proving the
        algo-order round trip still works end to end. Returns the placement ack
        (what the self-check validates the shape of)."""
        ack = await self.place_stop_market(
            symbol, "SELL", far_stop_price, quantity=quantity, reduce_only=False,
        )
        await self.cancel_algo_order(symbol, algo_id=ack.get("algoId"))
        return ack
