"""Idempotent client order ID generation.

PLAN_OF_ACTION.md §5: "Reconcile before retry — unchanged; idempotency via client
order IDs." A deterministic ID for the same (strategy, symbol, side, signal_time,
attempt) means a retry after a crash reuses the same ID; querying that ID against
the exchange before placing again is how "reconcile before retry" is implemented,
rather than risking a duplicate order.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from scalping.domain.models import Side


def make_client_order_id(
    *, strategy_version: str, symbol: str, side: Side, signal_time: datetime, attempt: int = 0
) -> str:
    basis = f"{strategy_version}:{symbol}:{side.value}:{int(signal_time.timestamp())}:{attempt}"
    digest = hashlib.sha256(basis.encode()).hexdigest()[:24]
    return f"scalp-{digest}"


def make_client_algo_id(
    *, purpose: str, strategy_version: str, symbol: str, side: Side, signal_time: datetime
) -> str:
    """`purpose` distinguishes the stop vs take-profit algo order derived from the
    same entry, so both are deterministic and never collide with each other or with
    the entry's client_order_id."""
    basis = (
        f"algo:{purpose}:{strategy_version}:{symbol}:{side.value}:"
        f"{int(signal_time.timestamp())}"
    )
    digest = hashlib.sha256(basis.encode()).hexdigest()[:24]
    return f"scalp-algo-{digest}"
