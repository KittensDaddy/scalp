"""Dynamic symbol universe builder — SCANNER_DASHBOARD_PLAN.md §D / Phase 1.

Funnel: `GET /fapi/v1/exchangeInfo` (PERPETUAL, quoteAsset=USDT, status=TRADING) ->
`GET /fapi/v1/ticker/24hr` batch (min quote volume) -> bookTicker snapshot (max
spread) -> kline-history availability (min history days). Every symbol gets a
`UniverseEntry` recording exactly which filters it passed/failed, so the dashboard
can show *why* a class is untradable instead of silently hiding it (design rule
carried over from `caems_presets.yaml`).
"""

from __future__ import annotations

from dataclasses import dataclass

from scalping.exchanges.binance.rest import BinanceRestClient


@dataclass(frozen=True)
class UniverseConfig:
    quote_asset: str = "USDT"
    min_quote_volume_usdt: float = 20_000_000.0
    max_spread_bps: float = 5.0
    min_history_days: int = 7


@dataclass(frozen=True)
class ExchangeSymbolInfo:
    symbol: str
    quote_asset: str
    contract_type: str
    status: str


@dataclass(frozen=True)
class UniverseEntry:
    symbol: str
    eligible: bool
    filters_passed: dict[str, bool]
    reasons: list[str]


@dataclass(frozen=True)
class UniverseChanged:
    added: list[str]
    removed: list[str]


def evaluate_universe(
    exchange_symbols: list[ExchangeSymbolInfo],
    quote_volume_by_symbol: dict[str, float],
    spread_bps_by_symbol: dict[str, float],
    history_days_by_symbol: dict[str, float],
    config: UniverseConfig,
) -> list[UniverseEntry]:
    """Pure filter logic — every symbol evaluated against every filter
    independently (not a short-circuiting cascade), so a rejected symbol's
    dashboard row can show *all* the reasons it fails, not just the first one.
    Network I/O and the cascading fetch-only-survivors optimization live in
    `build_universe` below.
    """
    entries: list[UniverseEntry] = []
    for sym in exchange_symbols:
        reasons: list[str] = []

        base_ok = (
            sym.contract_type == "PERPETUAL"
            and sym.quote_asset == config.quote_asset
            and sym.status == "TRADING"
        )
        if not base_ok:
            reasons.append("NOT_ELIGIBLE_CONTRACT")

        volume = quote_volume_by_symbol.get(sym.symbol)
        volume_ok = volume is not None and volume >= config.min_quote_volume_usdt
        if not volume_ok:
            reasons.append("LOW_VOLUME")

        spread = spread_bps_by_symbol.get(sym.symbol)
        spread_ok = spread is not None and spread <= config.max_spread_bps
        if not spread_ok:
            reasons.append("SPREAD_TOO_WIDE")

        if config.min_history_days <= 0:
            history_ok = True
        else:
            history = history_days_by_symbol.get(sym.symbol)
            history_ok = history is not None and history >= config.min_history_days
            if not history_ok:
                reasons.append("INSUFFICIENT_HISTORY")

        entries.append(
            UniverseEntry(
                symbol=sym.symbol,
                eligible=base_ok and volume_ok and spread_ok and history_ok,
                filters_passed={
                    "base_eligibility": base_ok, "volume": volume_ok,
                    "spread": spread_ok, "history": history_ok,
                },
                reasons=reasons,
            )
        )
    return entries


def diff_universe(previous_eligible: set[str], current_eligible: set[str]) -> UniverseChanged:
    return UniverseChanged(
        added=sorted(current_eligible - previous_eligible),
        removed=sorted(previous_eligible - current_eligible),
    )


def _spread_bps(book_ticker_raw: dict) -> float | None:
    try:
        bid, ask = float(book_ticker_raw["bidPrice"]), float(book_ticker_raw["askPrice"])
    except (KeyError, TypeError, ValueError):
        return None
    if bid <= 0 or ask <= 0:
        return None
    mid = (bid + ask) / 2
    return (ask - bid) / mid * 10_000


async def _kline_history_days(rest: BinanceRestClient, symbol: str) -> float:
    """Earliest available daily candle -> days of history, via a 1-candle query
    from epoch. Only called for symbols that already survive the volume+spread
    filters, keeping this network-heaviest step off the bulk of the universe."""
    import time

    candles = await rest.klines(symbol, "1d", start_ms=0, limit=1)
    if not candles:
        return 0.0
    earliest_open_ms = candles[0][0]
    return (time.time() * 1000 - earliest_open_ms) / (1000 * 60 * 60 * 24)


async def build_universe(rest: BinanceRestClient, config: UniverseConfig) -> list[UniverseEntry]:
    """Cascading network fetch — each stage only queries symbols that survived the
    previous stage, matching the funnel described in SCANNER_DASHBOARD_PLAN.md §D."""
    info = await rest.exchange_info()
    exchange_symbols = [
        ExchangeSymbolInfo(
            symbol=s["symbol"], quote_asset=s.get("quoteAsset", ""),
            contract_type=s.get("contractType", ""), status=s.get("status", ""),
        )
        for s in info.get("symbols", [])
    ]
    base_survivors = [
        s for s in exchange_symbols
        if s.contract_type == "PERPETUAL" and s.quote_asset == config.quote_asset
        and s.status == "TRADING"
    ]

    tickers = await rest.ticker_24hr()
    volume_by_symbol = {t["symbol"]: float(t.get("quoteVolume", 0.0)) for t in tickers}
    volume_survivors = [
        s for s in base_survivors
        if volume_by_symbol.get(s.symbol, 0.0) >= config.min_quote_volume_usdt
    ]

    book_tickers = await rest.book_ticker_all()
    spread_by_symbol = {
        b["symbol"]: spread for b in book_tickers if (spread := _spread_bps(b)) is not None
    }
    spread_survivors = [
        s for s in volume_survivors
        if spread_by_symbol.get(s.symbol, float("inf")) <= config.max_spread_bps
    ]

    # Per-symbol earliest-kline probes are ~1 REST call each and IP-ban easily
    # at 300-symbol scale. Default paper config sets min_history_days=0 to skip.
    history_by_symbol: dict[str, float] = {}
    if config.min_history_days > 0:
        for s in spread_survivors:
            history_by_symbol[s.symbol] = await _kline_history_days(rest, s.symbol)

    return evaluate_universe(
        exchange_symbols, volume_by_symbol, spread_by_symbol, history_by_symbol, config
    )
