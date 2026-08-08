"""`scalping` CLI entry point.

P1 scope: `--version` and `--check-config` only, enough to prove the foundation
boots. `--run` and `--dashboard` are wired in as later phases land (P7+, P10).
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from scalping import __version__
from scalping.config.settings import get_settings
from scalping.monitoring.logging import configure_logging
from scalping.persistence.engine import init_db, make_engine


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scalping")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument("--init-db", action="store_true")
    parser.add_argument("--run", action="store_true", help="not yet implemented (P7+)")
    parser.add_argument("--dashboard", action="store_true", help="not yet implemented (P10)")
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
    if args.run or args.dashboard:
        print("not yet implemented", file=sys.stderr)
        return 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
