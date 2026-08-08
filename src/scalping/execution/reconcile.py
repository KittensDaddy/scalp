"""Reconciliation — PLAN_OF_ACTION.md §K: "Process restart: OMS reconciliation from
exchange state (positions, open orders) before trading enabled; idempotent
clientOrderIds prevent dupes." Target metric (§8 evidence bar): zero unreconciled
positions across >=3 forced restarts and >=3 forced disconnects on testnet.

A "naked" position — open on the exchange with no matching stop/take-profit algo
order — is the specific failure mode this exists to catch; it is exactly what the
protection-gap mechanism (protection.py) is supposed to prevent, so finding one here
means that mechanism failed somewhere upstream.
"""

from __future__ import annotations

from dataclasses import dataclass

from scalping.domain.models import Side
from scalping.execution.ports import ExchangePort


@dataclass(frozen=True)
class LocalPositionRecord:
    symbol: str
    side: Side
    quantity: float


@dataclass(frozen=True)
class ReconcileMismatch:
    symbol: str
    kind: str  # "unexpected_exchange_position" | "missing_exchange_position" | "naked_position"
    detail: str


@dataclass(frozen=True)
class ReconcileReport:
    mismatches: list[ReconcileMismatch]

    @property
    def clean(self) -> bool:
        return not self.mismatches


async def reconcile(
    port: ExchangePort, expected: list[LocalPositionRecord]
) -> ReconcileReport:
    exchange_positions = await port.get_open_positions()
    exchange_by_symbol = {p.symbol: p for p in exchange_positions}
    expected_by_symbol = {e.symbol: e for e in expected}

    mismatches: list[ReconcileMismatch] = []

    for symbol, exch_pos in exchange_by_symbol.items():
        local = expected_by_symbol.get(symbol)
        if local is None:
            mismatches.append(
                ReconcileMismatch(
                    symbol, "unexpected_exchange_position",
                    f"exchange reports {exch_pos.side.value} {exch_pos.quantity} "
                    f"with no local record",
                )
            )
            continue
        if local.side != exch_pos.side or abs(local.quantity - exch_pos.quantity) > 1e-9:
            mismatches.append(
                ReconcileMismatch(
                    symbol, "unexpected_exchange_position",
                    f"local={local.side.value} {local.quantity} vs "
                    f"exchange={exch_pos.side.value} {exch_pos.quantity}",
                )
            )
            continue

        algo_orders = await port.get_open_algo_orders(symbol)
        has_stop = any(a.algo_type == "STOP_MARKET" for a in algo_orders)
        has_tp = any(a.algo_type == "TAKE_PROFIT_MARKET" for a in algo_orders)
        if not (has_stop and has_tp):
            missing = []
            if not has_stop:
                missing.append("stop")
            if not has_tp:
                missing.append("take_profit")
            mismatches.append(
                ReconcileMismatch(
                    symbol, "naked_position", f"missing algo orders: {', '.join(missing)}"
                )
            )

    for symbol, local in expected_by_symbol.items():
        if symbol not in exchange_by_symbol:
            mismatches.append(
                ReconcileMismatch(
                    symbol, "missing_exchange_position",
                    f"local expected {local.side.value} {local.quantity} but exchange shows none",
                )
            )

    return ReconcileReport(mismatches=mismatches)
