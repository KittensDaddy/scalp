"""`scalping` CLI entry point.

Supports `--version`, `--check-config`, `--init-db`, `--dashboard`, and `--run`.
`--run` starts the trading-loop supervisor with a real production tick (scanner +
optional paper execution) and serves the dashboard API on the same process so the
UI reflects live paper state.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import UTC, datetime, timedelta

import uvicorn
from sqlalchemy.ext.asyncio import async_sessionmaker

from scalping import __version__
from scalping.api.app import create_app
from scalping.api.broadcast import Broadcaster
from scalping.config.class_resolver import SymbolClassResolver, volume_ranks_from_tickers
from scalping.config.frozen import FrozenParams
from scalping.config.settings import get_settings
from scalping.exchanges.base.rate_limiter import RateLimiter
from scalping.exchanges.binance.rest import BinanceRestClient
from scalping.market_data.aggregation import aggregate_candles
from scalping.market_data.candles import fetch_klines_range, load_backtest_candles
from scalping.market_data.manager import MarketDataManager
from scalping.market_data.registry import SymbolStateRegistry
from scalping.monitoring.active_trades import ActiveTradeService
from scalping.monitoring.logging import configure_logging
from scalping.paper.venue import PaperVenue
from scalping.persistence.engine import init_db, make_engine
from scalping.risk.kill_switch import KillSwitch
from scalping.runtime.paper_executor import PaperExecutor
from scalping.runtime.supervisor import SupervisorConfig, TraderSupervisor
from scalping.runtime.tick import ProductionTick, load_caems_presets
from scalping.runtime.universe_refresh import fetch_ranked_universe, merge_universe
from scalping.scanner.developing import DevelopingSetupsService
from scalping.scanner.runner import StrategyRunner
from scalping.scanner.service import ScannerService

log = logging.getLogger(__name__)


def _check_config() -> int:
    settings = get_settings()
    configure_logging(settings)
    config_hash = settings.defaults.config_hash()
    print(f"environment: {settings.environment}")
    print(f"config_hash: {config_hash}")
    print(f"database_url: {settings.database_url}")
    print("OK")
    return 0


async def _init_db_async() -> None:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    await init_db(engine)
    await engine.dispose()


def _make_rest(settings) -> BinanceRestClient:
    return BinanceRestClient(
        base_url=settings.binance_rest_base,
        api_key=settings.binance_api_key,
        api_secret=settings.binance_api_secret,
        rate_limiter=RateLimiter(),
    )


def _candle_loader_factory(settings):
    rest = _make_rest(settings)

    async def loader(symbols, date_from, date_to):
        return await load_backtest_candles(
            rest, symbols=symbols, date_from=date_from, date_to=date_to
        )

    return loader


def _dashboard() -> int:
    settings = get_settings()
    configure_logging(settings)
    if not settings.control_token or not settings.dashboard_unkill_token:
        print(
            "SCALPING_CONTROL_TOKEN and SCALPING_DASHBOARD_UNKILL_TOKEN required",
            file=sys.stderr,
        )
        return 1
    engine = make_engine(settings.database_url)

    async def _prepare() -> None:
        await init_db(engine)

    asyncio.run(_prepare())
    kill_switch = KillSwitch(
        control_token=settings.control_token,
        unkill_token=settings.dashboard_unkill_token,
    )
    app = create_app(
        engine=engine,
        settings=settings,
        kill_switch=kill_switch,
        candle_loader=_candle_loader_factory(settings),
    )
    uvicorn.run(
        app,
        host=settings.dashboard_host,
        port=settings.dashboard_port,
        log_level="info",
    )
    return 0


async def _resolve_symbols(
    rest: BinanceRestClient,
    settings,
    session_factory,
) -> list[str]:
    """Explicit list, or liquid USDT-perp universe when run_symbols=auto."""
    if not settings.use_universe():
        symbols = settings.symbols_list()
        if not symbols:
            raise ValueError("SCALPING_RUN_SYMBOLS is empty")
        return symbols

    print("building liquid symbol universe from Binance…", flush=True)
    capped = await fetch_ranked_universe(rest, settings, session_factory)
    print(
        f"universe: using top {len(capped)} by 24h volume "
        f"(max={settings.universe_max_symbols} "
        f"min_vol={settings.universe_min_quote_volume_usdt:.0f} "
        f"max_spread_bps={settings.universe_max_spread_bps})",
        flush=True,
    )
    if not capped:
        raise RuntimeError("universe builder returned zero eligible symbols")
    return capped


async def _restart_ws(
    md: MarketDataManager, symbols: list[str], ws_tasks: list[asyncio.Task]
) -> list[asyncio.Task]:
    for conn in md._connections.values():
        conn.stop()
    for t in ws_tasks:
        t.cancel()
    if ws_tasks:
        await asyncio.gather(*ws_tasks, return_exceptions=True)
    md.rebalance(set(symbols))
    connections = md.build_connections()
    return [
        asyncio.create_task(conn.run(), name=f"ws-{key}")
        for key, conn in connections.items()
    ]


async def _warm_one(
    rest: BinanceRestClient,
    registry: SymbolStateRegistry,
    symbol: str,
    *,
    start: datetime,
    end: datetime,
    sem: asyncio.Semaphore,
) -> None:
    async with sem:
        try:
            # limit=500 keeps Binance kline weight low (280 bars fit in one page).
            candles = await fetch_klines_range(
                rest, symbol=symbol, interval="1m", start=start, end=end, limit=500
            )
            for candle in candles:
                registry.on_kline_1m_closed(candle)
            for c5 in aggregate_candles(candles, "5m"):
                registry.on_kline_5m_closed(c5)
        except Exception as exc:
            log.warning("warm failed for %s: %s", symbol, exc)


async def _warm_registry(
    rest: BinanceRestClient,
    registry: SymbolStateRegistry,
    symbols: list[str],
    *,
    bars: int = 280,
    concurrency: int = 2,
) -> None:
    """Seed indicators slowly — 300 symbols × klines will IP-ban if rushed."""
    end = datetime.now(UTC)
    start = end - timedelta(minutes=bars + 5)
    sem = asyncio.Semaphore(concurrency)
    await asyncio.gather(
        *[_warm_one(rest, registry, s, start=start, end=end, sem=sem) for s in symbols]
    )
    # One batch bookTicker instead of N per-symbol calls.
    await _poll_books(rest, registry, None, symbols)


async def _poll_books(
    rest: BinanceRestClient,
    registry: SymbolStateRegistry,
    venue: PaperVenue | None,
    symbols: list[str],
) -> None:
    """One batch bookTicker snapshot — safe for large universes (WS is primary)."""
    from scalping.domain.models import BookTicker

    wanted = set(symbols)
    try:
        rows = await rest.book_ticker_all()
    except Exception as exc:
        log.debug("book poll batch failed: %s", exc)
        return
    now = datetime.now(UTC)
    for raw in rows:
        symbol = raw.get("symbol") or raw.get("s")
        if symbol not in wanted:
            continue
        try:
            bid = float(raw.get("bidPrice") or raw.get("b"))
            ask = float(raw.get("askPrice") or raw.get("a"))
            bid_qty = float(raw.get("bidQty") or raw.get("B") or 0.0)
            ask_qty = float(raw.get("askQty") or raw.get("A") or 0.0)
        except (TypeError, ValueError):
            continue
        bt = BookTicker(
            symbol=symbol,
            bid_price=bid,
            bid_qty=bid_qty,
            ask_price=ask,
            ask_qty=ask_qty,
            event_time=now,
        )
        registry.on_book_ticker(bt)
        if venue is not None:
            venue.on_book_ticker(bt)


async def _run_async() -> int:
    settings = get_settings()
    configure_logging(settings)
    if not settings.control_token or not settings.dashboard_unkill_token:
        print(
            "SCALPING_CONTROL_TOKEN and SCALPING_DASHBOARD_UNKILL_TOKEN required",
            file=sys.stderr,
        )
        return 1

    engine = make_engine(settings.database_url)
    await init_db(engine)
    session_factory = async_sessionmaker(engine)
    rest = _make_rest(settings)

    try:
        symbols = await _resolve_symbols(rest, settings, session_factory)
    except Exception as exc:
        print(f"failed to resolve symbols: {exc}", file=sys.stderr)
        msg = str(exc)
        if "418" in msg or "banned until" in msg.lower() or "-1003" in msg:
            print(
                "Binance IP ban — wait until the timestamp clears, then retry.\n"
                "Universe no longer probes per-symbol kline history; warm is throttled.",
                file=sys.stderr,
            )
        await engine.dispose()
        return 1

    kill_switch = KillSwitch(
        control_token=settings.control_token,
        unkill_token=settings.dashboard_unkill_token,
    )
    frozen = FrozenParams()
    registry = SymbolStateRegistry(frozen)
    scanner = ScannerService()
    developing = DevelopingSetupsService()
    active_trades = ActiveTradeService()
    broadcaster = Broadcaster()
    config = settings.defaults

    presets = load_caems_presets(settings.presets_path or None)
    class_resolver = SymbolClassResolver(presets, defaults=config)
    enabled_ids: set[str] | None = None
    if settings.enabled_strategies.strip():
        enabled_ids = {
            s.strip() for s in settings.enabled_strategies.split(",") if s.strip()
        }
    runner = StrategyRunner(
        scanner=scanner, developing=developing, enabled_ids=enabled_ids
    )

    venue: PaperVenue | None = None
    paper_executor: PaperExecutor | None = None
    if settings.environment in ("paper", "backtest", "replay"):
        venue = PaperVenue()
        paper_executor = PaperExecutor(
            venue=venue,
            active_trades=active_trades,
            config=config,
            equity=settings.paper_equity,
            sessionmaker=session_factory,
            config_hash=config.config_hash(),
        )

    try:
        print(f"warming indicators for {len(symbols)} symbols…", flush=True)
        await _warm_registry(rest, registry, symbols)
        print(f"warmed registry ({len(symbols)} symbols)", flush=True)
    except Exception as exc:
        print(f"WARNING: registry warm failed ({exc}) — waiting for live feed", flush=True)

    volume_ranks: dict[str, int] = {}
    try:
        tickers = await rest.ticker_24hr()
        volume_ranks = volume_ranks_from_tickers(tickers)
    except Exception as exc:
        print(f"WARNING: volume ranks unavailable ({exc})", flush=True)

    # Mutable watchlist shared by tick / poll / refresh.
    watchlist = list(symbols)

    md = MarketDataManager(ws_base=settings.binance_ws_base, registry=registry)
    md.rebalance(set(watchlist))
    connections = md.build_connections()
    ws_tasks = [
        asyncio.create_task(conn.run(), name=f"ws-{key}")
        for key, conn in connections.items()
    ]

    tick = ProductionTick(
        registry=registry,
        runner=runner,
        scanner=scanner,
        developing=developing,
        active_trades=active_trades,
        broadcaster=broadcaster,
        kill_switch=kill_switch,
        config=config,
        symbols=watchlist,
        frozen=frozen,
        paper_executor=paper_executor,
        execute=settings.environment == "paper",
        class_resolver=class_resolver,
        volume_rank_by_symbol=volume_ranks,
    )

    async def on_tick(supervisor, now):
        await _poll_books(rest, registry, venue, watchlist)
        await tick(supervisor, now)

    supervisor = TraderSupervisor(
        kill_switch=kill_switch,
        scanner=scanner,
        developing=developing,
        active_trades=active_trades,
        broadcaster=broadcaster,
        config=SupervisorConfig(symbols=watchlist, eval_interval_s=1.0),
        on_tick=on_tick,
    )

    async def universe_refresh_loop() -> None:
        nonlocal ws_tasks
        if not settings.use_universe():
            return
        interval = max(0.25, float(settings.universe_refresh_hours)) * 3600.0
        while True:
            await asyncio.sleep(interval)
            try:
                ranked = await fetch_ranked_universe(rest, settings, session_factory)
                protect = {t.symbol for t in active_trades.snapshot().positions}
                nxt, added, removed = merge_universe(
                    previous=watchlist,
                    ranked=ranked,
                    protect=protect,
                    max_symbols=settings.universe_max_symbols,
                )
                if not added and not removed:
                    print(
                        f"universe refresh: no change ({len(watchlist)} symbols)",
                        flush=True,
                    )
                    continue
                if added:
                    print(f"universe refresh: warming {len(added)} new symbols…", flush=True)
                    await _warm_registry(rest, registry, added)
                watchlist[:] = nxt
                tick.symbols = watchlist
                supervisor.config.symbols = watchlist
                try:
                    tick.update_volume_ranks(await rest.ticker_24hr())
                except Exception:
                    log.exception("volume rank refresh failed")
                ws_tasks = await _restart_ws(md, watchlist, ws_tasks)
                print(
                    f"universe refresh: now {len(watchlist)} "
                    f"(+{len(added)} / -{len(removed)}); "
                    f"open-position protect={sorted(protect)}",
                    flush=True,
                )
            except Exception as exc:
                log.exception("universe refresh failed: %s", exc)

    app = create_app(
        engine=engine,
        settings=settings,
        kill_switch=kill_switch,
        scanner_service=scanner,
        registry=registry,
        broadcaster=broadcaster,
        developing_service=developing,
        active_trades_service=active_trades,
        candle_loader=_candle_loader_factory(settings),
    )
    uv_config = uvicorn.Config(
        app,
        host=settings.dashboard_host,
        port=settings.dashboard_port,
        log_level="info",
    )
    server = uvicorn.Server(uv_config)

    await supervisor.start()
    refresh_task = asyncio.create_task(universe_refresh_loop(), name="universe_refresh")
    print(
        f"scalping --run started env={settings.environment} "
        f"symbols={len(watchlist)} "
        f"presets={len(presets)} "
        f"strategies={enabled_ids or 'default'} "
        f"refresh_h={settings.universe_refresh_hours} "
        f"dashboard={settings.dashboard_host}:{settings.dashboard_port}",
        flush=True,
    )
    try:
        await server.serve()
    finally:
        refresh_task.cancel()
        await supervisor.stop()
        for t in ws_tasks:
            t.cancel()
        await asyncio.gather(refresh_task, *ws_tasks, return_exceptions=True)
        await engine.dispose()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scalping")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument("--init-db", action="store_true")
    parser.add_argument("--run", action="store_true", help="start trading-loop + dashboard API")
    parser.add_argument("--dashboard", action="store_true", help="serve FastAPI dashboard only")
    args = parser.parse_args(argv)

    if args.version:
        print(__version__)
        return 0
    if args.check_config:
        return _check_config()
    if args.init_db:
        asyncio.run(_init_db_async())
        print("OK")
        return 0
    if args.dashboard:
        return _dashboard()
    if args.run:
        return asyncio.run(_run_async())

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
