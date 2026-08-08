"""Protection gap — PLAN_OF_ACTION.md §5a, the load-bearing safety mechanism.

With stops on a separate endpoint from the GTX entry, a fill->protected window is
unavoidable. It is a measured, bounded quantity:

- `t_protection = ACK(stop) & ACK(tp) - fill_time`, per trade.
- **Hard rule:** if protection unconfirmed within `protection_timeout_ms` (default
  2000 ms) -> emergency reduce-only market close + kill switch + incident. Retried
  placement happens *within* the window, not instead of it.

Also implements the breakeven move (strategy-caems.md §Exit logic): one amendment
only, and the amended stop must never move away from price.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime

from scalping.domain.models import Side
from scalping.execution.ports import ExchangePort


class ProtectionTimeoutIncident(Exception):
    """Raised (and must trigger kill switch + incident) when protection is not
    confirmed within `protection_timeout_ms`."""

    def __init__(self, symbol: str, elapsed_ms: float) -> None:
        self.symbol = symbol
        self.elapsed_ms = elapsed_ms
        super().__init__(
            f"protection unconfirmed for {symbol} after {elapsed_ms:.0f}ms — "
            f"emergency close + kill switch required"
        )


@dataclass(frozen=True)
class ProtectionResult:
    protected: bool
    t_protection_ms: float
    stop_algo_id: str | None
    tp_algo_id: str | None


async def establish_protection(
    *,
    port: ExchangePort,
    symbol: str,
    side: Side,
    quantity: float,
    stop_price: float,
    tp_price: float,
    fill_time: datetime,
    protection_timeout_ms: int,
    client_algo_id_stop: str,
    client_algo_id_tp: str,
) -> ProtectionResult:
    """Places stop + TP concurrently and measures t_protection against `fill_time`.

    On timeout, raises :class:`ProtectionTimeoutIncident` — the caller (trading
    loop) is responsible for the emergency reduce-only close + kill switch engage +
    incident recording; this function's job is purely to measure and enforce the
    bound, not to own those side effects (keeps this module testable without a
    kill-switch/incident dependency).
    """
    start = time.monotonic()

    async def _place_both() -> tuple:
        stop_task = port.place_stop(symbol, side, stop_price, quantity, client_algo_id_stop)
        tp_task = port.place_take_profit(symbol, side, tp_price, quantity, client_algo_id_tp)
        return await asyncio.gather(stop_task, tp_task)

    timeout_s = protection_timeout_ms / 1000.0
    try:
        stop_ack, tp_ack = await asyncio.wait_for(_place_both(), timeout=timeout_s)
    except Exception:
        elapsed_ms = (time.monotonic() - start) * 1000.0
        raise ProtectionTimeoutIncident(symbol, elapsed_ms) from None

    elapsed_ms = (time.monotonic() - start) * 1000.0
    if elapsed_ms > protection_timeout_ms:
        raise ProtectionTimeoutIncident(symbol, elapsed_ms)

    return ProtectionResult(
        protected=True, t_protection_ms=elapsed_ms,
        stop_algo_id=stop_ack.algo_id, tp_algo_id=tp_ack.algo_id,
    )


def compute_breakeven_stop(
    *, side: Side, entry_price: float, round_trip_cost_price_units: float
) -> float:
    """strategy-caems.md: amend to entry + be_offset (offset = round-trip cost in
    price units), so a stop-out at breakeven is a true scratch, not a small loss."""
    if side is Side.LONG:
        return entry_price + round_trip_cost_price_units
    return entry_price - round_trip_cost_price_units


def breakeven_move_allowed(
    *, side: Side, current_stop: float, new_stop: float, already_moved: bool
) -> bool:
    """One amendment only; never move the stop away from price."""
    if already_moved:
        return False
    if side is Side.LONG:
        return new_stop > current_stop
    return new_stop < current_stop


async def apply_breakeven_move(
    *,
    port: ExchangePort,
    symbol: str,
    side: Side,
    client_algo_id_stop: str,
    current_stop: float,
    entry_price: float,
    round_trip_cost_price_units: float,
    already_moved: bool,
) -> float | None:
    """Returns the new stop price if the amendment was applied, else None."""
    new_stop = compute_breakeven_stop(
        side=side, entry_price=entry_price, round_trip_cost_price_units=round_trip_cost_price_units
    )
    if not breakeven_move_allowed(
        side=side, current_stop=current_stop, new_stop=new_stop, already_moved=already_moved
    ):
        return None
    await port.amend_stop(symbol, client_algo_id_stop, new_stop)
    return new_stop
