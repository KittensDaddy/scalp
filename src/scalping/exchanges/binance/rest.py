"""Signed Binance USDS-M Futures REST client.

PLAN_OF_ACTION.md §2: base `https://fapi.binance.com` (testnet
`https://demo-fapi.binance.com`), HMAC-SHA256 signing with `X-MBX-APIKEY`,
`timestamp` + `recvWindow`. Rate-limited per :class:`~scalping.exchanges.base.
rate_limiter.RateLimiter` with a caller-supplied :class:`Budget` per call, so order
traffic, algo-order traffic, market-data polling, and backfill never share a bucket.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

import httpx

from scalping.exchanges.base.errors import ExchangeError, OrderRejected, RateLimited
from scalping.exchanges.base.rate_limiter import Budget, RateLimiter


class BinanceRestClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        api_secret: str,
        rate_limiter: RateLimiter,
        recv_window_ms: int = 5000,
        http_client: httpx.AsyncClient | None = None,
        proxy: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._api_secret = api_secret.encode()
        self._rate_limiter = rate_limiter
        self._recv_window_ms = recv_window_ms
        if http_client is not None:
            self._client = http_client
        else:
            kwargs: dict[str, Any] = {"base_url": self._base_url, "timeout": 30.0}
            if proxy:
                kwargs["proxy"] = proxy
            self._client = httpx.AsyncClient(**kwargs)
        self.proxy = proxy

    def _sign(self, params: dict[str, Any]) -> dict[str, Any]:
        params = dict(params)
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = self._recv_window_ms
        query = "&".join(f"{k}={v}" for k, v in params.items())
        signature = hmac.new(self._api_secret, query.encode(), hashlib.sha256).hexdigest()
        params["signature"] = signature
        return params

    async def request(
        self,
        method: str,
        path: str,
        *,
        budget: Budget,
        params: dict[str, Any] | None = None,
        signed: bool = False,
    ) -> Any:
        """Public low-level entry point, shared with `algo_orders.py` for the
        algoOrder endpoints which reuse this same signing/rate-limit/error path."""
        await self._rate_limiter.acquire(budget)
        params = params or {}
        headers = {}
        if signed:
            params = self._sign(params)
        if self._api_key:
            headers["X-MBX-APIKEY"] = self._api_key

        resp = await self._client.request(method, path, params=params, headers=headers)
        if resp.status_code == 429 or resp.status_code == 418:
            raise RateLimited(f"exchange returned {resp.status_code}: {resp.text}")
        if resp.status_code >= 400:
            try:
                body = resp.json()
                code = body.get("code", resp.status_code)
                msg = body.get("msg", resp.text)
            except ValueError:
                code, msg = resp.status_code, resp.text
            from scalping.exchanges.base.errors import LegacyConditionalOrderRejected

            if code == -4120:
                raise LegacyConditionalOrderRejected(code, msg)
            raise OrderRejected(code, msg)
        try:
            return resp.json()
        except ValueError as e:
            raise ExchangeError(f"non-JSON response from {path}: {resp.text[:200]}") from e

    # -- public/market endpoints --------------------------------------------------

    async def exchange_info(self) -> dict[str, Any]:
        return await self.request("GET", "/fapi/v1/exchangeInfo", budget=Budget.MARKET)

    async def ticker_24hr(self) -> list[dict[str, Any]]:
        return await self.request("GET", "/fapi/v1/ticker/24hr", budget=Budget.MARKET)

    async def book_ticker(self, symbol: str) -> dict[str, Any]:
        return await self.request(
            "GET", "/fapi/v1/ticker/bookTicker", budget=Budget.MARKET, params={"symbol": symbol}
        )

    async def book_ticker_all(self) -> list[dict[str, Any]]:
        """No `symbol` param -> Binance returns bookTicker for every symbol in one
        call; used by universe building instead of one request per symbol."""
        return await self.request("GET", "/fapi/v1/ticker/bookTicker", budget=Budget.MARKET)

    async def klines(
        self, symbol: str, interval: str, *, start_ms: int | None = None,
        end_ms: int | None = None, limit: int = 500, budget: Budget = Budget.MARKET,
    ) -> list[list[Any]]:
        params: dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_ms is not None:
            params["startTime"] = start_ms
        if end_ms is not None:
            params["endTime"] = end_ms
        return await self.request("GET", "/fapi/v1/klines", budget=budget, params=params)

    # -- trading/account endpoints (signed) ----------------------------------------

    async def new_order(self, **params: Any) -> dict[str, Any]:
        """Entries and plain orders — NOT conditional (`STOP_*`/`TAKE_PROFIT_*`)
        orders, which now return -4120 here since the algo-order migration
        (PLAN_OF_ACTION.md §2); those go through `algo_orders.py`."""
        return await self.request(
            "POST", "/fapi/v1/order", budget=Budget.ORDER, params=params, signed=True
        )

    async def cancel_order(self, symbol: str, *, order_id: int | None = None,
                            orig_client_order_id: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"symbol": symbol}
        if order_id is not None:
            params["orderId"] = order_id
        if orig_client_order_id is not None:
            params["origClientOrderId"] = orig_client_order_id
        return await self.request(
            "DELETE", "/fapi/v1/order", budget=Budget.ORDER, params=params, signed=True
        )

    async def query_order(self, symbol: str, *, order_id: int | None = None,
                           orig_client_order_id: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"symbol": symbol}
        if order_id is not None:
            params["orderId"] = order_id
        if orig_client_order_id is not None:
            params["origClientOrderId"] = orig_client_order_id
        return await self.request(
            "GET", "/fapi/v1/order", budget=Budget.ORDER, params=params, signed=True
        )

    async def position_risk(self, symbol: str | None = None) -> list[dict[str, Any]]:
        params = {"symbol": symbol} if symbol else {}
        return await self.request(
            "GET", "/fapi/v2/positionRisk", budget=Budget.ORDER, params=params, signed=True
        )

    async def listen_key_create(self) -> dict[str, Any]:
        return await self.request(
            "POST", "/fapi/v1/listenKey", budget=Budget.MARKET, signed=False
        )

    async def listen_key_keepalive(self) -> dict[str, Any]:
        return await self.request(
            "PUT", "/fapi/v1/listenKey", budget=Budget.MARKET, signed=False
        )

    async def aclose(self) -> None:
        await self._client.aclose()
