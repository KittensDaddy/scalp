from __future__ import annotations

import httpx

from scalping.exchanges.base.rate_limiter import RateLimiter
from scalping.exchanges.binance.algo_orders import AlgoOrderClient
from scalping.exchanges.binance.rest import BinanceRestClient


def _algo_client_with_handler(handler) -> AlgoOrderClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(base_url="https://demo-fapi.binance.com", transport=transport)
    rest = BinanceRestClient(
        base_url="https://demo-fapi.binance.com",
        api_key="k",
        api_secret="s",
        rate_limiter=RateLimiter(),
        http_client=http_client,
    )
    return AlgoOrderClient(rest)


async def test_place_stop_market_hits_algo_order_endpoint():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        params = dict(httpx.QueryParams(request.url.query))
        seen["params"] = params
        return httpx.Response(200, json={"algoId": 1, "symbol": "BTCUSDT", "algoType": "STOP_MARKET"})

    client = _algo_client_with_handler(handler)
    result = await client.place_stop_market("BTCUSDT", "SELL", 99.0, close_position=True)

    assert seen["path"] == "/fapi/v1/algoOrder"
    assert seen["params"]["algoType"] == "STOP_MARKET"
    assert result["algoId"] == 1


async def test_place_take_profit_market_hits_algo_order_endpoint():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"algoId": 2, "symbol": "BTCUSDT", "algoType": "TAKE_PROFIT_MARKET"}
        )

    client = _algo_client_with_handler(handler)
    result = await client.place_take_profit_market("BTCUSDT", "SELL", 101.0, close_position=True)
    assert result["algoType"] == "TAKE_PROFIT_MARKET"


async def test_cancel_algo_order():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        return httpx.Response(200, json={"algoId": 1, "symbol": "BTCUSDT", "algoType": "STOP_MARKET"})

    client = _algo_client_with_handler(handler)
    await client.cancel_algo_order("BTCUSDT", algo_id=1)


async def test_submit_and_cancel_minimal_stop_places_then_cancels():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "POST":
            return httpx.Response(
                200, json={"algoId": 42, "symbol": "BTCUSDT", "algoType": "STOP_MARKET"}
            )
        return httpx.Response(200, json={"algoId": 42, "symbol": "BTCUSDT", "algoType": "STOP_MARKET"})

    client = _algo_client_with_handler(handler)
    ack = await client.submit_and_cancel_minimal_stop("BTCUSDT", far_stop_price=1.0, quantity=0.001)

    assert calls == ["POST", "DELETE"]
    assert ack["algoId"] == 42
