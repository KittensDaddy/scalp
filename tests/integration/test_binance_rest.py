from __future__ import annotations

import httpx
import pytest

from scalping.exchanges.base.errors import (
    LegacyConditionalOrderRejected,
    OrderRejected,
    RateLimited,
)
from scalping.exchanges.base.rate_limiter import RateLimiter
from scalping.exchanges.binance.rest import BinanceRestClient


def _client_with_handler(handler) -> BinanceRestClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(
        base_url="https://demo-fapi.binance.com", transport=transport
    )
    return BinanceRestClient(
        base_url="https://demo-fapi.binance.com",
        api_key="test-key",
        api_secret="test-secret",
        rate_limiter=RateLimiter(),
        http_client=http_client,
    )


async def test_exchange_info_happy_path():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/fapi/v1/exchangeInfo"
        return httpx.Response(200, json={"symbols": [{"symbol": "BTCUSDT"}]})

    client = _client_with_handler(handler)
    result = await client.exchange_info()
    assert result["symbols"][0]["symbol"] == "BTCUSDT"


async def test_signed_request_includes_signature_and_apikey_header():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = request.headers
        seen["query"] = dict(httpx.QueryParams(request.url.query))
        return httpx.Response(200, json={"orderId": 1})

    client = _client_with_handler(handler)
    await client.new_order(symbol="BTCUSDT", side="BUY", type="LIMIT", timeInForce="GTX")

    assert seen["headers"]["X-MBX-APIKEY"] == "test-key"
    assert "signature" in seen["query"]
    assert "timestamp" in seen["query"]
    assert "recvWindow" in seen["query"]


async def test_429_raises_rate_limited():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="too many requests")

    client = _client_with_handler(handler)
    with pytest.raises(RateLimited):
        await client.exchange_info()


async def test_dash_4120_raises_legacy_conditional_order_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"code": -4120, "msg": "Order type not supported"})

    client = _client_with_handler(handler)
    with pytest.raises(LegacyConditionalOrderRejected):
        await client.new_order(symbol="BTCUSDT", side="BUY", type="STOP_MARKET")


async def test_generic_error_raises_order_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"code": -1013, "msg": "Invalid quantity"})

    client = _client_with_handler(handler)
    with pytest.raises(OrderRejected):
        await client.new_order(symbol="BTCUSDT", side="BUY", type="MARKET", quantity=0)


async def test_klines_passes_through_market_budget():
    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(httpx.QueryParams(request.url.query))
        assert params["symbol"] == "BTCUSDT"
        assert params["interval"] == "1m"
        return httpx.Response(200, json=[[1, "1", "1", "1", "1", "1"]])

    client = _client_with_handler(handler)
    result = await client.klines("BTCUSDT", "1m")
    assert len(result) == 1
