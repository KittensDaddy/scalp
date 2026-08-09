"""Periodic liquid-universe refresh for `--run`.

Two clocks, intentionally separate:
- **Scanner score** (every tick): which watched symbols look most promising *now*.
- **Universe membership** (every few hours): which liquid USDT-perps we bother to
  watch at all. Refresh here; do not confuse with score ranking.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import async_sessionmaker

from scalping.config.settings import Settings
from scalping.exchanges.binance.rest import BinanceRestClient
from scalping.market_data.universe import UniverseConfig, build_universe
from scalping.persistence.universe_repo import upsert_universe

log = logging.getLogger(__name__)

_PRIORITY = {"BTCUSDT": 0, "ETHUSDT": 1}


def universe_config_from_settings(settings: Settings) -> UniverseConfig:
    return UniverseConfig(
        min_quote_volume_usdt=settings.universe_min_quote_volume_usdt,
        max_spread_bps=settings.universe_max_spread_bps,
        min_history_days=settings.universe_min_history_days,
    )


async def fetch_ranked_universe(
    rest: BinanceRestClient,
    settings: Settings,
    session_factory: async_sessionmaker,
) -> list[str]:
    """Eligible symbols ranked by 24h quote volume (majors pinned first)."""
    cfg = universe_config_from_settings(settings)
    entries = await build_universe(rest, cfg)
    async with session_factory() as session:
        await upsert_universe(
            session, entries, now=datetime.now(UTC).replace(tzinfo=None)
        )
        await session.commit()

    eligible = [e.symbol for e in entries if e.eligible]
    if not eligible:
        return []

    tickers = await rest.ticker_24hr()
    vol = {t["symbol"]: float(t.get("quoteVolume", 0.0)) for t in tickers}
    eligible.sort(key=lambda s: (_PRIORITY.get(s, 100), -vol.get(s, 0.0), s))
    return eligible[: settings.universe_max_symbols]


def merge_universe(
    *,
    previous: list[str],
    ranked: list[str],
    protect: set[str],
    max_symbols: int,
) -> tuple[list[str], list[str], list[str]]:
    """Apply a refresh while keeping open-position symbols.

    Returns (next_symbols, added, removed).
    """
    protect = {s.upper() for s in protect}
    ranked = list(ranked)
    # Force protected symbols into the set even if they fell out of liquidity.
    for sym in sorted(protect):
        if sym not in ranked:
            ranked.insert(0, sym)
    # Dedupe preserving order
    seen: set[str] = set()
    next_syms: list[str] = []
    for s in ranked:
        if s in seen:
            continue
        seen.add(s)
        next_syms.append(s)
        if len(next_syms) >= max_symbols and protect.issubset(seen):
            break
    # If protect pushed us over, trim non-protected from the end
    while len(next_syms) > max_symbols:
        for i in range(len(next_syms) - 1, -1, -1):
            if next_syms[i] not in protect:
                next_syms.pop(i)
                break
        else:
            break

    prev_set, next_set = set(previous), set(next_syms)
    added = sorted(next_set - prev_set)
    removed = sorted(prev_set - next_set)
    return next_syms, added, removed
