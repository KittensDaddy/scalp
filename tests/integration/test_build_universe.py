from __future__ import annotations

import time

import httpx

from scalping.exchanges.base.rate_limiter import RateLimiter
from scalping.exchanges.binance.rest import BinanceRestClient
from scalping.market_data.universe import UniverseConfig, build_universe


def _make_symbols(n: int) -> list[dict]:
    return [
        {"symbol": f"SYM{i}USDT", "quoteAsset": "USDT", "contractType": "PERPETUAL", "status": "TRADING"}
        for i in range(n)
    ]


def _client_with_handler(handler) -> BinanceRestClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(base_url="https://demo-fapi.binance.com", transport=transport)
    return BinanceRestClient(
        base_url="https://demo-fapi.binance.com", api_key="k", api_secret="s",
        rate_limiter=RateLimiter(), http_client=http_client,
    )


async def test_build_universe_end_to_end_yields_100_plus_eligible():
    n = 150
    old_ms = int(time.time() * 1000) - 30 * 24 * 60 * 60 * 1000  # 30 days ago

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/fapi/v1/exchangeInfo":
            return httpx.Response(200, json={"symbols": _make_symbols(n)})
        if path == "/fapi/v1/ticker/24hr":
            return httpx.Response(
                200,
                json=[{"symbol": f"SYM{i}USDT", "quoteVolume": "50000000"} for i in range(n)],
            )
        if path == "/fapi/v1/ticker/bookTicker":
            return httpx.Response(
                200,
                json=[
                    {"symbol": f"SYM{i}USDT", "bidPrice": "100.0", "askPrice": "100.01"}
                    for i in range(n)
                ],
            )
        if path == "/fapi/v1/klines":
            return httpx.Response(200, json=[[old_ms, "1", "1", "1", "1", "1"]])
        raise AssertionError(f"unexpected path {path}")

    client = _client_with_handler(handler)
    entries = await build_universe(client, UniverseConfig())

    eligible = [e for e in entries if e.eligible]
    assert len(eligible) >= 100
    assert len(entries) == n


async def test_build_universe_skips_klines_when_history_disabled():
    kline_calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/fapi/v1/exchangeInfo":
            return httpx.Response(200, json={"symbols": _make_symbols(3)})
        if path == "/fapi/v1/ticker/24hr":
            return httpx.Response(
                200,
                json=[{"symbol": f"SYM{i}USDT", "quoteVolume": "50000000"} for i in range(3)],
            )
        if path == "/fapi/v1/ticker/bookTicker":
            return httpx.Response(
                200,
                json=[
                    {"symbol": f"SYM{i}USDT", "bidPrice": "100.0", "askPrice": "100.01"}
                    for i in range(3)
                ],
            )
        if path == "/fapi/v1/klines":
            kline_calls.append("hit")
            return httpx.Response(200, json=[])
        raise AssertionError(f"unexpected path {path}")

    client = _client_with_handler(handler)
    entries = await build_universe(client, UniverseConfig(min_history_days=0))
    assert kline_calls == []
    assert sum(1 for e in entries if e.eligible) == 3


async def test_build_universe_cascades_skip_ineligible_symbols():
    """Symbols failing the volume filter should never trigger a kline history
    fetch — the cascade must actually skip stages, not just report them skipped."""
    kline_calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/fapi/v1/exchangeInfo":
            return httpx.Response(200, json={"symbols": _make_symbols(2)})
        if path == "/fapi/v1/ticker/24hr":
            return httpx.Response(
                200,
                json=[
                    {"symbol": "SYM0USDT", "quoteVolume": "50000000"},
                    {"symbol": "SYM1USDT", "quoteVolume": "1"},  # too low
                ],
            )
        if path == "/fapi/v1/ticker/bookTicker":
            return httpx.Response(
                200, json=[{"symbol": "SYM0USDT", "bidPrice": "100.0", "askPrice": "100.01"}]
            )
        if path == "/fapi/v1/klines":
            params = dict(httpx.QueryParams(request.url.query))
            kline_calls.append(params["symbol"])
            old_ms = int(time.time() * 1000) - 30 * 24 * 60 * 60 * 1000
            return httpx.Response(200, json=[[old_ms, "1", "1", "1", "1", "1"]])
        raise AssertionError(f"unexpected path {path}")

    client = _client_with_handler(handler)
    entries = await build_universe(client, UniverseConfig())

    assert kline_calls == ["SYM0USDT"]
    by_symbol = {e.symbol: e for e in entries}
    assert by_symbol["SYM0USDT"].eligible is True
    assert by_symbol["SYM1USDT"].eligible is False
    assert "LOW_VOLUME" in by_symbol["SYM1USDT"].reasons
